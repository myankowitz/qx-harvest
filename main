#!/usr/bin/env python3
"""
Quantum X weekly paper harvester
  • Scrapes faculty names   (https://www.quantumx.washington.edu/people/?profile_type=qx-faculty)
  • Maps each name → OpenAlex author-ID
  • Collects works published since --days (default 7)
  • Emits digest.md   – Markdown list
           digest.bib – BibTeX file
Run:  python qx_harvest.py [--days 7]
"""

import argparse, datetime, json, re, sys, textwrap, pathlib
from typing import List, Dict, Optional

import httpx
from bs4 import BeautifulSoup

QX_URL   = "https://www.quantumx.washington.edu/people/?profile_type=qx-faculty"
OUT_MD   = pathlib.Path("digest.md")
OUT_BIB  = pathlib.Path("digest.bib")
HEADERS  = {"User-Agent": "qx-harvest/1.0 (+https://github.com/YOURNAME/qx-harvest)"}


# ─────────────────────────────────────────────────────────────────────────────
# 1.  Scrape faculty roster
# ─────────────────────────────────────────────────────────────────────────────
def fetch_faculty() -> List[str]:
    """Return list of faculty names scraped from Quantum X directory page."""
    html = httpx.get(QX_URL, headers=HEADERS, timeout=30).text
    soup = BeautifulSoup(html, "html.parser")

    names: List[str] = []
    for p in soup.select("p"):
        first = p.contents[0] if p.contents else None
        if first and getattr(first, "name", None) == "a":
            txt = first.get_text(strip=True)
            # crude human-name heuristic: at least 2 words, no "@" or "/" etc.
            if len(txt.split()) >= 2 and not re.search(r"[@/]|Quantum|NSF|UW", txt):
                names.append(txt)

    # de-duplicate while preserving order
    seen = set()
    roster = [n for n in names if not (n in seen or seen.add(n))]
    return roster


# ─────────────────────────────────────────────────────────────────────────────
# 2.  Map name → OpenAlex author-ID
# ─────────────────────────────────────────────────────────────────────────────
def openalex_id(name: str) -> Optional[str]:
    """Resolve a human name to an OpenAlex author ID (best guess)."""
    url = f"https://api.openalex.org/authors?search={httpx.utils.quote(name)}&per_page=5"
    try:
        results = httpx.get(url, headers=HEADERS, timeout=30).json()["results"]
    except Exception:
        return None

    # Pick first result that mentions UW; else first result overall.
    for r in results:
        inst = (r.get("last_known_institution") or {}).get("display_name", "")
        if "University of Washington" in inst:
            return r["id"].split("/")[-1]
    return results[0]["id"].split("/")[-1] if results else None


# ─────────────────────────────────────────────────────────────────────────────
# 3.  Pull works since date
# ─────────────────────────────────────────────────────────────────────────────
def works_since(author_id: str, since_iso: str) -> List[Dict]:
    url = (
        "https://api.openalex.org/works?"
        f"filter=author.id:{author_id},from_publication_date:{since_iso}"
        "&sort=publication_date:desc&per_page=200"
    )
    return httpx.get(url, headers=HEADERS, timeout=60).json().get("results", [])


# ─────────────────────────────────────────────────────────────────────────────
# 4.  Assemble digest & BibTeX
# ─────────────────────────────────────────────────────────────────────────────
def bibtex_entry(work: Dict) -> str:
    doi = work.get("doi", "") or "TODO"
    key = doi.split("/")[-1] if doi else re.sub(r"\W+", "", work["display_name"])[:20]
    authors = ", ".join(a["author"]["display_name"] for a in work["authorships"])
    journal = (work["primary_location"]["source"] or {}).get("display_name", "arXiv")
    year = work["publication_year"]
    title = work["display_name"]
    return textwrap.dedent(
        f"""\
        @article{{{key},
          title   = {{{title}}},
          author  = {{{authors}}},
          journal = {{{journal}}},
          year    = {{{year}}},
          doi     = {{{doi}}}
        }}"""
    )


def main(days_back: int):
    since_date = (datetime.date.today() - datetime.timedelta(days=days_back)).isoformat()
    print(f"📋  Collecting works since {since_date}")

    roster = fetch_faculty()
    print(f"👩‍🔬  {len(roster)} faculty scraped")

    author_map = {n: openalex_id(n) for n in roster}
    missing = [n for n, aid in author_map.items() if aid is None]
    if missing:
        print("⚠️  OpenAlex ID not found:", ", ".join(missing), file=sys.stderr)

    papers: Dict[str, Dict] = {}
    for name, aid in author_map.items():
        if not aid:
            continue
        for w in works_since(aid, since_date):
            doi = w.get("doi") or w["id"]  # fall back to OpenAlex ID
            papers.setdefault(doi, w)  # de-dupe across co-authors

    # ── write Markdown digest ────────────────────────────────────────────
    md_lines = [
        "# Quantum X – new papers",
        f"*generated {datetime.date.today()} – last {days_back} days*",
        "",
    ]
    for w in sorted(papers.values(), key=lambda x: x["publication_date"], reverse=True):
        doi = w.get("doi")
        link = f"https://doi.org/{doi}" if doi else w["id"]
        title = w["display_name"]
        journal = (w["primary_location"]["source"] or {}).get("display_name", "arXiv")
        date = w["publication_date"]
        md_lines.append(f"- **{title}**  \n  {journal} ({date})  \n  {link}\n")

    OUT_MD.write_text("\n".join(md_lines))
    OUT_BIB.write_text("\n\n".join(bibtex_entry(w) for w in papers.values()))

    print(f"✅  {len(papers)} works written to {OUT_MD} and {OUT_BIB}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Quantum X weekly paper harvester")
    ap.add_argument("--days", type=int, default=7, help="look-back window in days")
    args = ap.parse_args()
    main(args.days)
