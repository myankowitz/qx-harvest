import streamlit as st
from typing import List, Dict
import datetime as _dt

from qx_harvest import (
    fetch_faculty,
    works_openalex,
    works_arxiv,
    openalex_meta,
)

# ─────────────────────────── general layout ──────────────────────────────
st.set_page_config(page_title="Quantum X Paper Harvester", layout="wide")
st.title("Quantum X – On‑demand Paper Lists (no caching)")

st.markdown(
    "Choose a look‑back window for **either** source and click its button. "
    "This version prioritises correctness over speed – no data are cached, "
    "so each click fetches fresh results."
)

# ─────────────────────────── helpers ─────────────────────────────────────

def unique_titles(papers: List[Dict]) -> List[Dict]:
    seen = set()
    out = []
    for p in papers:
        t = p.get("display_name", "").lower()
        if t and t not in seen:
            seen.add(t)
            out.append(p)
    return out


def format_authors(p: Dict) -> str:
    if "authorships" in p:
        names = [a["author"]["display_name"] for a in p["authorships"]]
    else:
        names = p.get("authors", [])
    if not names:
        return "Unknown"
    return f"{names[0]} et al." if len(names) > 20 else ", ".join(names)


def format_citation(p: Dict) -> str:
    authors = format_authors(p)
    title = p.get("display_name", "Untitled")
    year = p.get("publication_year") or p.get("publication_date", "????")[:4]
    journal = p.get("source", "arXiv") or "arXiv"

    # strip generic arXiv label if we have a real venue
    if journal.lower().startswith("arxiv") and p.get("doi"):
        journal = ""

    pages = ""
    if (b := p.get("biblio")) and (f := b.get("first_page")) and (l := b.get("last_page")):
        pages = f" {f}-{l}"

    # build URL sensibly
    url = ""
    if (doi := p.get("doi")):
        if doi.startswith("http"):
            url = doi
        else:
            url = f"https://doi.org/{doi}"
    elif p.get("id", "").startswith("arXiv:"):
        url = f"https://arxiv.org/abs/{p['id'].split(':')[1]}"

    citation = f"{authors}. *{title}*. {journal}{pages} ({year})."
    if url:
        citation += f" [[link]]({url})"
    return citation


# ─────────────────────────── data collectors ─────────────────────────────

def collect_openalex(days_back: int) -> List[Dict]:
    """Fetch works via OpenAlex and attach a clean journal/source name."""
    since_iso = (_dt.date.today() - _dt.timedelta(days=days_back)).isoformat()
    out: Dict[str, Dict] = {}
    for name in fetch_faculty():
        oa_id, _ = openalex_meta(name)
        if not oa_id:
            continue
        for w in works_openalex(oa_id, since_iso):
            # 1️⃣ pick the best available venue label
            src_primary = (
                (
                    w.get("primary_location", {})
                    or {}
                ).get("source", {})
                or {}
            ).get("display_name", "")
            src_host = (w.get("host_venue", {}) or {}).get("display_name", "")
            src = src_primary or src_host or ""
            cleaned = {**w, "source": src}
            out.setdefault(cleaned.get("doi") or cleaned["id"], cleaned)
    return list(out.values())


def collect_arxiv(days_back: int) -> List[Dict]:
    since_date = _dt.date.today() - _dt.timedelta(days=days_back)
    out: Dict[str, Dict] = {}
    for name in fetch_faculty():
        for w in works_arxiv(name, since_date):
            out.setdefault(w["id"], w)
    return list(out.values())


# ─────────────────────────── UI elements ─────────────────────────────────

placeholder = st.empty()  # area to display results, replaced each run

col_oa, col_ax = st.columns(2)

with col_oa:
    days_oa = st.slider("OpenAlex look‑back (days)", 7, 365, 90, 7, key="oa")
    if st.button("Fetch from OpenAlex", key="btn_oa"):
        with st.spinner("Querying OpenAlex …"):
            papers = collect_openalex(days_oa)
        papers = sorted(unique_titles(papers), key=lambda x: x["publication_date"], reverse=True)
        md = "\n".join(f"- {format_citation(p)}" for p in papers) or "No papers found."
        placeholder.markdown(md)

with col_ax:
    days_ax = st.slider("arXiv look‑back (days)", 7, 365, 90, 7, key="ax")
    if st.button("Fetch from arXiv", key="btn_ax"):
        with st.spinner("Querying arXiv …"):
            papers = collect_arxiv(days_ax)
        papers = sorted(unique_titles(papers), key=lambda x: x["publication_date"], reverse=True)
        md = "\n".join(f"- {format_citation(p)}" for p in papers) or "No papers found."
        placeholder.markdown(md)

if not (st.session_state.get("btn_oa") or st.session_state.get("btn_ax")):
    st.info("Select a window and press one of the buttons above to generate a list.")
