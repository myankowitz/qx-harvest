import streamlit as st
from typing import List, Dict
import datetime as _dt

# Pull only the lightweight helpers we need from qx_harvest
from qx_harvest import (
    fetch_faculty,
    works_openalex,
    works_arxiv,
    openalex_meta,
)

st.set_page_config(page_title="Quantum X Paper Harvester", layout="wide")
st.title("Quantum X – On‑demand Paper Lists")

st.markdown(
    "Pick a look‑back window for **either** data source and click its button. "
    "Only the chosen API is queried, so results arrive quickly."
)

# ─────────────────────────── helper utilities ─────────────────────────────

def unique_titles(papers: List[Dict]) -> List[Dict]:
    """Remove duplicates by case‑insensitive title."""
    seen = set()
    uniq = []
    for p in papers:
        key = p.get("display_name", "").lower()
        if key and key not in seen:
            seen.add(key)
            uniq.append(p)
    return uniq


@st.cache_data(ttl=600)
def get_faculty() -> List[str]:
    return fetch_faculty()


@st.cache_data(ttl=600)
def collect_openalex(days_back: int) -> List[Dict]:
    since_iso = (_dt.date.today() - _dt.timedelta(days=days_back)).isoformat()
    out: Dict[str, Dict] = {}
    for name in get_faculty():
        oa_id, _ = openalex_meta(name)
        if not oa_id:
            continue
        for w in works_openalex(oa_id, since_iso):
            out.setdefault(w.get("doi") or w["id"], w)
    return list(out.values())


@st.cache_data(ttl=600)
def collect_arxiv(days_back: int) -> List[Dict]:
    since_date = _dt.date.today() - _dt.timedelta(days=days_back)
    out: Dict[str, Dict] = {}
    for name in get_faculty():
        for w in works_arxiv(name, since_date):
            out.setdefault(w["id"], w)
    return list(out.values())


def _format_authors(p: Dict) -> str:
    if "authorships" in p:
        authors = [a["author"]["display_name"] for a in p["authorships"]]
    else:
        authors = p.get("authors", [])
    if not authors:
        return "Unknown"
    return f"{authors[0]} et al." if len(authors) > 20 else ", ".join(authors)


def _format_citation(p: Dict) -> str:
    authors = _format_authors(p)
    title = p.get("display_name", "Untitled")
    year = p.get("publication_year") or p.get("publication_date", "????")[:4]
    journal = p.get("source", "arXiv") or "arXiv"

    pages = ""
    if (b := p.get("biblio")) and (f := b.get("first_page")) and (l := b.get("last_page")):
        pages = f" {f}-{l}"

    url = ""
    if p.get("doi"):
        url = f"https://doi.org/{p['doi']}"
    elif p.get("id", "").startswith("arXiv:"):
        url = f"https://arxiv.org/abs/{p['id'].split(':')[1]}"

    citation = f"{authors}. *{title}*. {journal}{pages} ({year})."
    if url:
        citation += f" [[link]]({url})"
    return citation


def _display(papers: List[Dict]):
    if not papers:
        st.warning("No papers found in that window.")
        return
    papers = sorted(unique_titles(papers), key=lambda x: x["publication_date"], reverse=True)
    md = "\n".join(f"- {_format_citation(p)}" for p in papers)
    st.markdown(md)


# ───────────────────────────── UI layout ───────────────────────────────────
col_oa, col_ax = st.columns(2)

with col_oa:
    days_oa = st.slider("OpenAlex look‑back (days)", 7, 365, 90, 7, key="oa")
    if st.button("Fetch from OpenAlex", key="btn_oa"):
        with st.spinner("Querying OpenAlex …"):
            _display(collect_openalex(days_oa))

with col_ax:
    days_ax = st.slider("arXiv look‑back (days)", 7, 365, 90, 7, key="ax")
    if st.button("Fetch from arXiv", key="btn_ax"):
        with st.spinner("Querying arXiv …"):
            _display(collect_arxiv(days_ax))

if not (st.session_state.get("btn_oa") or st.session_state.get("btn_ax")):
    st.info("Select a window and press one of the buttons to generate a list.")
