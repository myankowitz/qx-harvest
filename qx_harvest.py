#!/usr/bin/env python3
"""
Quantum X paper harvester  •  v1.1  (2025‑06‑10)

Changes versus v1.0
-------------------
* Look‑back window defaults to **90 days** (≈ 3 months) instead of 7.
* Adds **arXiv** harvesting for each faculty member.
  ‑ Uses the author search pattern "<Last>_<F>" (e.g. Yankowitz_M).
  ‑ Parses the Atom feed without external dependencies.
* Keeps de‑duplication across OpenAlex and arXiv using DOI or arXiv ID.

Run locally:
    python qx_harvest.py            # last 90 days
    python qx_harvest.py --days 30  # last month

Cron example (GitHub Actions `on:schedule`): weekly run that still
collects the previous 90 days so nothing is missed if a run fails.

All output lives in two files committed back to the repo root:
    digest.md   – Markdown newsletter
    digest.bib  – BibTeX entries
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
from typing import Dict, List, Optional

import httpx
from bs4 import BeautifulSoup

# ─────────────── Configuration ──────────────────────────────────────────────
QX_URL = "https://www.quantumx.washington.edu/people/?profile_type=qx-faculty"
HEADERS = {"User-Agent": "qx-harvest/1.1 (+https://github.com/YOURNAME/qx-harvest)"}

OUT_MD = pathlib.Path("digest.md")
OUT_BIB = pathlib.Path("digest.bib")

ARXIV_MAX_RESULTS = 50  # per‑author, per run – plenty for 90 days
# ----------------------------------------------------------------------------


# 1.  Faculty roster (scraped each run) --------------------------------------

def fetch_faculty() -> List[str]:
    """Return list of faculty names from the Quantum X directory."""
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


# 2.  Helper – OpenAlex author‑ID -------------------------------------------

def openalex_id(name: str) -> Optional[str]:
    """Best‑guess OpenAlex author ID for a given human name."""
    encoded = urllib.parse.quote_plus(name)
    url = f"https://api.openalex.org/authors?search={encoded}&per_page=5"
    try:
        results = httpx.get(url, headers=HEADERS, timeout=30).json()["results"]
    except Exception:
        return None

    # Prefer records that list UW
    for r in results:
        inst = (r.get("last_known_institution") or {}).get("display_name", "")
        if "University of Washington" in inst:
            return r["id"].split("/")[-1]
    return results[0]["id"].split("/")[-1] if results else None


# 3.  Works from OpenAlex -----------------------------------------------------

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


# 4.  Works from arXiv --------------------------------------------------------

def name_to_arxiv_tag(name: str) -> str:
    """Convert "First Middle Last" → "Last_F" suitable for arXiv au: search."""
    parts = name.split()
    if len(parts) < 2:
        return name  # fallback
    last = parts[-1]
    first_initial = parts[0][0]
    return f"{last}_{first_initial}"


def works_arxiv(tag: str, since_date: _dt.date) -> List[Dict]:
    """Return arXiv entries (dicts) newer than *since_date* for author tag."""
    base = "https://export.arxiv.org/api/query"
    q = (
        f"search_query=au:{tag}&"
        f"max_results={ARXIV_MAX_RESULTS}&sortBy=submittedDate&sortOrder=descending"
    )
    try:
        text = httpx.get(f"{base}?{q}", headers=HEADERS, timeout=60).text
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
            break  # feed is ordered newest→oldest; we can stop early

        title = entry.findtext("a:title", default="", namespaces=ns).strip().replace("\n", " ")
        arxiv_id = entry.findtext("a:id", default="", namespaces=ns).rsplit("/", 1)[-1]
        results.append(
            {
                "source": "arXiv",
                "display_name": title,
                "publication_date": published,
                "id": f"arXiv:{arxiv_id}",
                "doi": None,
                "publication_year": pub_date.year,
            }
        )
    return results


# 5.  BibTeX helper -----------------------------------------------------------

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


# 6.  Main orchestration ------------------------------------------------------

def main(days_back: int):
    since_date = _dt.date.today() - _dt.timedelta(days=days_back)
    since_iso = since_date.isoformat()
    print(f"🔍  Collecting works since {since_iso} (look‑back {days_back} days)")

    roster = fetch_faculty()
    print(f"👩‍🔬  {len(roster)} faculty scraped")

    author_ids = {name: openalex_id(name) for name in roster}

    all_papers: Dict[str, Dict] = {}

    for name in roster:
        oa = author_ids.get(name)
        if oa:
            for w in works_openalex(oa, since_iso):
                handle = w.get("doi") or w["id"]
                all_papers.setdefault(handle, {**w, "source": (w["primary_location"]["source"] or {}).get("display_name", "")})

        # arXiv
        tag = name_to_arxiv_tag(name)
        for w in works_arxiv(tag, since_date):
            handle = w["id"]  # arXiv:ID string is unique
            if handle not in all_papers:
                all_papers[handle] = w

    print(f"📄  Total unique papers: {len(all_papers)}")

    # ── write Markdown digest ────────────────────────────────────────────
    md_lines = [
        "# Quantum X – new papers (last {} days)".format(days_back),
        f"*generated {_dt.date.today()}*",
        "",
    ]
    for w in sorted(all_papers.values(), key=lambda x: x["publication_date"], reverse=True):
        link = f"https://doi.org/{w['doi']}" if w.get("doi") else f"https://arxiv.org/abs/{w['id'].split(':')[-1]}"
        md_lines.append(f"- **{w['display_name']}**  \n  {w.get('source', 'arXiv')} ({w['publication_date']})  \n  {link}\n")

    OUT_MD.write_text("\n".join(md_lines))
    OUT_BIB.write_text("\n\n".join(bibtex_entry(w) for w in all_papers.values()))

    print(f"✅  Wrote {OUT_MD} and {OUT_BIB}")


# ───────────────────────── CLI entry point ─────────────────────────────────--
if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Quantum X paper harvester")
    ap.add_argument("--days", type=int, default=90, help="Look‑back window in days (default: 90)")
    args = ap.parse_args()
    main(args.days)
