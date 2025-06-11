import streamlit as st
from typing import List, Dict
import datetime as _dt
from qx_harvest import collect_papers

st.set_page_config(page_title="Quantum X Paper Harvester", layout="wide")
st.title("Quantum X – On‑demand Paper Lists")

st.markdown(
    "Pick a look‑back window for **either** data source and click its button. "
    "The list below will refresh with the corresponding papers."
)

# ─────────────────────────── helper functions ──────────────────────────────

def _unique_by_title(papers: List[Dict]) -> List[Dict]:
    """Return papers with duplicate titles (case‑insensitive) removed."""
    seen = set()
    uniq = []
    for p in papers:
        t = p.get("display_name", "").lower()
        if t and t not in seen:
            seen.add(t)
            uniq.append(p)
    return uniq


def _format_authors(p: Dict) -> str:
    """Return author list with 'et al.' rule (>20 authors)."""
    authors: List[str] = []
    if "authorships" in p:  # OpenAlex
        authors = [a["author"]["display_name"] for a in p["authorships"]]
    elif "authors" in p:   # arXiv we stored
        authors = p["authors"]

    if not authors:
        return "Unknown"
    if len(authors) > 20:
        return f"{authors[0]} et al."
    return ", ".join(authors)


def _format_citation(p: Dict) -> str:
    title = p.get("display_name", "Untitled")
    year = p.get("publication_year") or p.get("publication_date", "????")[:4]

    authors = _format_authors(p)

    journal = p.get("source", "arXiv") or "arXiv"
    issue = ""
    pages = ""
    if "biblio" in p:
        b = p["biblio"]
        issue = b.get("issue", "")
        fpage = b.get("first_page", "")
        lpage = b.get("last_page", "")
        if fpage and lpage:
            pages = f"{fpage}-{lpage}"
    if pages and issue:
        volpart = f" {issue}:{pages}"
    elif issue:
        volpart = f" {issue}"
    elif pages:
        volpart = f" {pages}"
    else:
        volpart = ""

    url = ""
    if p.get("doi"):
        url = f"https://doi.org/{p['doi']}"
    elif p.get("id", "").startswith("arXiv:"):
        url = f"https://arxiv.org/abs/{p['id'].split(':')[1]}"

    citation = f"{authors}. *{title}*. {journal}{volpart} ({year})."
    if url:
        citation += f" [[link]]({url})"
    return citation


def _show_list(papers: List[Dict]):
    if not papers:
        st.warning("No papers found in that window.")
        return
    papers = sorted(_unique_by_title(papers), key=lambda x: x["publication_date"], reverse=True)
    md_lines = ["\n".join(_format_citation(p) for p in papers)]
    st.markdown("\n\n".join(md_lines))


# ────────────────────────────── UI layout ─────────────────────────────────
col_oa, col_ax = st.columns(2)

with col_oa:
    days_oa = st.slider("OpenAlex look‑back (days)", 7, 365, 90, 7, key="oa")
    if st.button("Fetch from OpenAlex"):
        with st.spinner("Querying OpenAlex …"):
            all_papers = collect_papers(days_oa)
            oa_papers = [p for p in all_papers if p.get("source", "") != "arXiv"]
        _show_list(oa_papers)

with col_ax:
    days_ax = st.slider("arXiv look‑back (days)", 7, 365, 90, 7, key="ax")
    if st.button("Fetch from arXiv"):
        with st.spinner("Querying arXiv …"):
            all_papers = collect_papers(days_ax)
            ax_papers = [p for p in all_papers if p.get("source", "") == "arXiv"]
        _show_list(ax_papers)

# Always show a gentle prompt when no button has been pressed
if not (st.session_state.get("Fetch from OpenAlex") or st.session_state.get("Fetch from arXiv")):
    st.info("Select a window and press one of the buttons to generate a list.")
