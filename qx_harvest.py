#!/usr/bin/env python3
"""
Quantum X paper harvester  •  v1.2  (2025‑06‑10)

Key improvements over v1.1
--------------------------
1. **Name‑accurate arXiv filter**
   * For each faculty member we now verify that the *full author name* appears in the `<author>` list of every arXiv entry, eliminating false positives like "X. Xu" that are not *Xiaodong Xu*.
2. **Crossref backup via ORCID**
   * If the author has an ORCID (fetched once from OpenAlex) we ask Crossref for anything published in the look‑back window.  This recovers papers where the author is hidden in a very long list and OpenAlex has not yet ingested the record.
3. **Config‑free – still one file, no extra packages, same CLI**

Usage examples
--------------
    python qx_harvest.py            # default 90‑day window
    python qx_harvest.py --days 30  # last month

The GitHub Actions workflow needs **no changes**.  Your existing schedule and
manual trigger will run the updated logic automatically.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import pathlib
import re
import textwrap
import urllib.parse
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Tuple

import httpx
from bs4 import BeautifulSoup

# ─────────────── Configuration ──────────────────────────────────────────────
QX_URL = "https://www.quantumx.washington.edu/people/?profile_type=qx-faculty"
HEADERS = {"User-Agent": "qx-harvest/1.2 (+https://github.com/YOURNAME/qx-harvest)"}

OUT_MD = pathlib.Path("digest.md")
OUT_BIB = pathlib.Path("digest.bib")

ARXIV_MAX_RESULTS = 100   # generous for 90 days even in large collaborations

# ----------------------------------------------------------------------------

# Helper: fast cache so we don't ask OpenAlex or Crossref repeatedly in one run
_CACHE: Dict[str, any] = {}

# 1.  Faculty roster ----------------------------------------------------------

def fetch_faculty() -> List[str]:
    """Return list of canonical faculty names from the Quantum X directory."""
    html = httpx.get(QX_URL, headers=HEADERS, timeout=30).text
    soup = BeautifulSoup(html, "html.parser")

    names: List[str] = []
    for p in soup.select("p"):
        first = p.contents[0] if p.contents else None
        if first and getattr(first, "name", None) == "a":
            txt = first.get_text(strip=True)
            if len(txt.split()) >= 2:
                names.append(txt)

    seen = set()
    return [n for n in names if not (n in seen or seen.add(n))]


# 2.  Author metadata via OpenAlex -------------------------------------------

def openalex_meta(name: str) -> Tuple[Optional[str], Optional[str]]:
    """Return (openalex_id, orcid) for a human name, caching results in‑run."""
    if name in _CACHE:
        return _CACHE[name]  # type: ignore[arg-type]

    encoded = urllib.parse.quote_plus(name)
    url = f"https://api.openalex.org/authors?search={encoded}&per_page=5"
    try:
        results = httpx.get(url, headers=HEADERS, timeout=30).json()["results"]
    except Exception:
        _CACHE[name] = (None, None)
        return (None, None)

    chosen = None
    for r in results:
        inst = (r.get("last_known_institution") or {}).get("display_name", "")
        if "University of Washington" in inst:
            chosen = r
            break
    if not chosen and results:
        chosen = results[0]

    if chosen:
        oa_id = chosen["id"].split("/")[-1]
        orcid = chosen.get("orcid")
        _CACHE[name] = (oa_id, orcid)
        return oa_id, orcid

    _CACHE[name] = (None, None)
    return (None, None)


# 3.  Works from OpenAlex ------------------------------------------------------

def works_openalex(author_id: str, since_iso: str) -> List[Dict]:
    url = (
        "https://api.openalex.org/works?"
        f"filter=author.id:{author_id},from_publication_date:{since_iso}"
        "&sort=publication_date:desc&per_page=200"
    )
    try:
        return httpx.get(url, headers=HEADERS, timeout=60).json().get("results", [])
    except Exception:
        return []


# 4.  Works from Crossref via ORCID ------------------------------------------

def works_crossref(orcid: str, since_date: _dt.date) -> List[Dict]:
    url = (
        "https://api.crossref.org/works?"
        f"filter=orcid:{orcid},from-pub-date:{since_date.isoformat()}"
        "&rows=200&sort=published&order=desc"
    )
    try:
        items = httpx.get(url, headers=HEADERS, timeout=60).json()["message"]["items"]
    except Exception:
        return []

    results = []
    for it in items:
        issued = it.get("issued", {}).get("date-parts", [[]])[0]
        if not issued:
            continue
        year = issued[0]
        month = issued[1] if len(issued) > 1 else 1
        day = issued[2] if len(issued) > 2 else 1
        pub_date = _dt.date(year, month, day)
        if pub_date < since_date:
            break
        results.append(
            {
                "id": it.get("DOI", it.get("url", "crossref:" + it.get("title", ["?"])[0][:20])),
                "display_name": it.get("title", ["Untitled"])[0],
                "doi": it.get("DOI"),
                "publication_date": pub_date.isoformat(),
                "publication_year": year,
                "source": it.get("container-title", ["Crossref"])[0] or "Crossref",
            }
        )
    return results


# 5.  Works from arXiv ---------------------------------------------------------

def arxiv_author_query(name: str) -> str:
    """Return a query string that prefers exact full name."""
    quoted = urllib.parse.quote_plus(f'"{name}"')
    return f"au:{quoted}"


def author_name_match(entry_authors: List[str], target: str) -> bool:
    """Return True if *target* appears among *entry_authors* with reasonable fuzz."""
    t_last, t_first = target.split()[-1].lower(), target.split()[0][0].lower()
    t_full = target.lower()
    for a in entry_authors:
        a_clean = a.lower()
        if a_clean == t_full:
            return True
        parts = re.split(r",\s*|\s+", a_clean)
        if len(parts) >= 2:
            last, first = parts[0], parts[-1][0]
            if last == t_last and first == t_first:
                return True
    return False


def works_arxiv(name: str, since_date: _dt.date) -> List[Dict]:
    base = "https://export.arxiv.org/api/query"
    q = arxiv_author_query(name)
    url = (
        f"{base}?search_query={q}&max_results={ARXIV_MAX_RESULTS}"
        "&sortBy=submittedDate&sortOrder=descending"
    )
    try:
        text = httpx.get(url, headers=HEADERS, timeout=60).text
    except Exception:
        return []

    root = ET.fromstring(text)
    ns = {"a": "http://www.w3.org/2005/Atom"}
    results = []

    for entry in root.findall("a:entry", ns):
        published = entry.findtext("a:published", default="", namespaces=ns)[:10]
        if not published:
            continue
        pub_date = _dt.date.fromisoformat(published)
        if pub_date < since_date:
            break  # entries are ordered newest→oldest

        # exact author matching to avoid homonyms
        authors = [e.findtext("a:name", namespaces=ns) for e in entry.findall("a:author", ns)]
        if not author_name_match(authors, name):
            continue

        title = entry.findtext("a:title", default="", namespaces=ns).strip().replace("\n", " ")
        arxiv_id = entry.findtext("a:id", default="", namespaces=ns).rsplit("/", 1)[-1]
        results.append(
            {
                "id": f"arXiv:{arxiv_id}",
                "display_name": title,
                "doi": None,
                "publication_date": published,
                "publication_year": pub_date.year,
                "source": "arXiv",
            }
        )
    return results


# 6.  BibTeX helper -----------------------------------------------------------

def bibtex_entry(work: Dict) -> str:
    doi = work.get("doi") or ""
    key = doi.split("/")[-1] if doi else re.sub(r"\W+", "", work["id"])[:20]
    title = work["display_name"]
    journal = work.get("source", "arXiv")
    year = work.get("publication_year", "????")
    return textwrap.dedent(
        f"""\
        @article{{{key},
          title   = {{{title}}},
          journal = {{{journal}}},
          year    = {{{year}}},
          doi     = {{{doi}}}
        }}"""
    )


# 7.  Main orchestration ------------------------------------------------------

def main(days_back: int):
    since_date = _dt.date.today() - _dt.timedelta(days=days_back)
    since_iso = since_date.isoformat()
    print(f"🔍  Collecting works since {since_iso} (look‑back {days_back} days)")

    roster = fetch_faculty()
    print(f"👩‍🔬  {len(roster)} faculty scraped")

    all_papers: Dict[str, Dict] = {}

    for name in roster:
        oa_id, orcid = openalex_meta(name)

        if oa_id:
            for w in works_openalex(oa_id, since_iso):
                handle = w.get("doi") or w["id"]
                all_papers.setdefault(handle, {**w, "source": (w["primary_location"]["source"] or {}).get("display_name", "")})

        if orcid:
            for w in works_crossref(orcid, since_date):
                handle = w.get("doi") or w["id"]
                all_papers.setdefault(handle, w)

        for w in works_arxiv(name, since_date):
            handle = w["id"]
            all_papers.setdefault(handle, w)

    print(f"📄  Total unique papers: {len(all_papers)}")

    # ── write Markdown digest ────────────────────────────────────────────
    md_lines = [
        "# Quantum X – new papers (last {} days)".format(days_back),
        f"*generated {_dt.date.today()}*",
        "",
    ]
    for w in sorted(all_papers.values(), key=lambda x: x["publication_date"], reverse=True):
        if w.get("doi"):
            link = f"https://doi.org/{w['doi']}"
        elif w["id"].startswith("arXiv:"):
            link = f"https://arxiv.org/abs/{w['id'].split(':')[1]}"
        else:
            link = ""
        md_lines.append(f"- **{w['display_name']}**  \n  {w.get('source', '—')} ({w['publication_date']})  \n  {link}\n")

    OUT_MD.write_text("\n".join(md_lines))
    OUT_BIB.write_text("\n\n".join(bibtex_entry(w) for w in all_papers.values()))

    print(f"✅  Wrote {OUT_MD} and {OUT_BIB}")


# ───────────────────────── CLI entry point ─────────────────────────────────--
if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Quantum X paper harvester (v1.2)")
    ap.add_argument("--days", type=int, default=90, help="Look‑back window in days (default: 90)")
    args = ap.parse_args()
    main(args.days)
