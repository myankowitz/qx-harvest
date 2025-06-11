import streamlit as st
from typing import List, Dict
import datetime as _dt
import httpx, bs4

from qx_harvest import (
    works_openalex,
    works_arxiv,
    openalex_meta,
)

# ─────────────────────────── page setup ───────────────────────────────────
st.set_page_config(page_title="Quantum X Paper Harvester v2", layout="wide")
st.title("Quantum X – On-demand Paper Lists (v2)")

st.markdown(
    "Choose a look‑back window for **either** source and click its button. "
    "The sliders stay at the top; the paper list appears below, followed by "
    "the roster of Quantum X researchers actually included in the search."
)

# ─────────────────────────── constants ─────────────────────────────────────
QX_URL = "https://www.quantumx.washington.edu/people/?profile_type=qx-faculty"
HEADERS = {"User-Agent": "qx-harvest/streamlit-v2"}

# ─────────────────────────── helper utilities ─────────────────────────────

def scrape_faculty() -> List[str]:
    """Scrape Quantum X faculty names and drop non‑person entries."""
    html = httpx.get(QX_URL, headers=HEADERS, timeout=30).text
    soup = bs4.BeautifulSoup(html, "html.parser")

    raw: List[str] = []
    # modern cards
    raw += [e.get_text(strip=True) for e in soup.select("h3.person-title, .people-card-name")]
    # legacy <h4><a>
    raw += [a.get_text(strip=True) for a in soup.select("h4 a[href]")]

    # validation regex: 2‑4 words, each starts with capital, letters or hyphen
    import re
    name_re = re.compile(r"^(?:[A-Z][A-Za-z\-]+ ){1,3}[A-Z][A-Za-z\-]+$")
    names = [n for n in raw if name_re.match(n)]

    # dedupe, preserve order
    seen, uniq = set(), []
    for n in names:
        if n not in seen:
            seen.add(n); uniq.append(n)
    return uniq


def unique_titles(papers: List[Dict]) -> List[Dict]:
    seen, out = set(), []
    for p in papers:
        key = p.get("display_name", "").lower()
        if key and key not in seen:
            seen.add(key); out.append(p)
    return out


def format_authors(p: Dict) -> str:
    names = [a["author"]["display_name"] for a in p.get("authorships", [])] or p.get("authors", [])
    if not names:
        return "Unknown"
    return f"{names[0]} et al." if len(names) > 20 else ", ".join(names)


def format_citation(p: Dict) -> str:
    authors = format_authors(p)
    title = p.get("display_name", "Untitled")
    year = p.get("publication_year") or p.get("publication_date", "????")[:4]
    journal = p.get("source", "arXiv") or "arXiv"
    if journal.lower().startswith("arxiv") and p.get("doi"):
        journal = ""

    pages = ""
    if (b := p.get("biblio")) and (f := b.get("first_page")) and (l := b.get("last_page")):
        pages = f" {f}-{l}"

    url = ""
    if (doi := p.get("doi")):
        url = doi if doi.startswith("http") else f"https://doi.org/{doi}"
    elif p.get("id", "").startswith("arXiv:"):
        url = f"https://arxiv.org/abs/{p['id'].split(':')[1]}"

    cite = f"{authors}. *{title}*. {journal}{pages} ({year})."
    return f"{cite} [[link]]({url})" if url else cite

# ─────────────────────────── data collectors ─────────────────────────────

def collect_openalex(days_back: int, faculty: List[str]) -> List[Dict]:
    since_iso = (_dt.date.today() - _dt.timedelta(days=days_back)).isoformat()
    out: Dict[str, Dict] = {}
    for name in faculty:
        oa_id, _ = openalex_meta(name)
        if not oa_id:
            continue
        for w in works_openalex(oa_id, since_iso):
            src_primary = ((w.get("primary_location", {}) or {}).get("source", {}) or {}).get("display_name", "")
            src_host = (w.get("host_venue", {}) or {}).get("display_name", "")
            src = src_primary or src_host or ""
            cleaned = {**w, "source": src}
            out.setdefault(cleaned.get("doi") or cleaned["id"], cleaned)
    return list(out.values())


def collect_arxiv(days_back: int, faculty: List[str]) -> List[Dict]:
    since_date = _dt.date.today() - _dt.timedelta(days=days_back)
    out: Dict[str, Dict] = {}
    for name in faculty:
        for w in works_arxiv(name, since_date):
            out.setdefault(w["id"], w)
    return list(out.values())


def build_markdown(papers: List[Dict]) -> str:
    if not papers:
        return "No papers found."
    papers = unique_titles(papers)
    papers.sort(key=lambda x: x["publication_date"], reverse=True)
    return "\n".join(f"- {format_citation(p)}" for p in papers)

# ─────────────────────────── main UI ──────────────────────────────────────
roster = scrape_faculty()

col_oa, col_ax = st.columns(2)

with col_oa:
    days_oa = st.slider("OpenAlex look‑back (days)", 7, 365, 90, 7, key="oa")
    if st.button("Fetch from OpenAlex", key="btn_oa"):
        with st.spinner("Querying OpenAlex …"):
            papers_md = build_markdown(collect_openalex(days_oa, roster))
        st.session_state["papers_md"] = papers_md
        st.session_state["roster_md"] = "**Researchers included:** " + ", ".join(roster)

with col_ax:
    days_ax = st.slider("arXiv look‑back (days)", 7, 365, 90, 7, key="ax")
    if st.button("Fetch from arXiv", key="btn_ax"):
        with st.spinner("Querying arXiv …"):
            papers_md = build_markdown(collect_arxiv(days_ax, roster))
        st.session_state["papers_md"] = papers_md
        st.session_state["roster_md"] = "**Researchers included:** " + ", ".join(roster)

# Display area below controls
st.markdown(st.session_state.get("papers_md", ""))
st.markdown(st.session_state.get("roster_md", ""))

if "papers_md" not in st.session_state:
    st.info("Select a window and press one of the buttons above to generate a list.")
