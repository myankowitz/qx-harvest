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
    """Return a robust list of faculty names from the Quantum X directory.

    The public site has changed HTML layouts over time.  We therefore try a
    series of increasingly loose selectors until we collect > 0 names.
    """
    html = httpx.get(QX_URL, headers=HEADERS, timeout=30).text
    soup = bs4.BeautifulSoup(html, "html.parser")

    # helper to deduplicate while preserving order
    def _dedupe(seq: List[str]) -> List[str]:
        seen, out = set(), []
        for s in seq:
            if s and s not in seen:
                seen.add(s); out.append(s)
        return out

    selectors = [
        "h4 a[href]",                 # legacy card layout
        "h3.person-title",            # current WP People plugin
        ".people-card-name",          # alternate card grid
        "figure.person
 figcaption", # older <figure> layout (space is newline)
    ]

    names: List[str] = []
    for sel in selectors:
        names = [e.get_text(strip=True) for e in soup.select(sel)]
        names = [n for n in names if len(n.split()) >= 2]  # simple sanity check
        if names:
            break

    # as a last‑ditch fallback, grab any anchor tags inside the main content that
    # look like names (two�words, capitalised)
    if not names:
        for a in soup.find_all("a"):
            txt = a.get_text(strip=True)
            if txt.count(" ") >= 1 and txt[0].isupper():
                names.append(txt)
        names = names[:50]  # keep list reasonable

    return _dedupe(names)


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
