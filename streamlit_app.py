import streamlit as st
from typing import List, Dict
import datetime as _dt
import httpx
from qx_harvest import works_openalex, works_arxiv, openalex_meta

# ─────────────────────────── Config ───────────────────────────────────────
HEADERS = {"User-Agent": "QuantumX-harvester/0.3"}

FACULTY: List[str] = [
    "Andrea Coladangelo", "Anton Andreev", "Arka Majumdar", "Arthur Barnard",
    "Boris Blinov", "Brandi Cossairt", "Charles Marcus", "Chinmay Nirkhe",
    "Daniel R. Gamelin", "David Cobden", "David Ginger", "David Hertzog",
    "David Masiello", "Di Xiao", "James Lee", "Jerry Li",
    "Jiun-Haw Chu", "Juan Carlos Idrobo", "Kai-Mei Fu", "Karl Böhringer",
    "Lukasz Fidkowski", "Mark Rudner", "Martin Savage", "Matthew Yankowitz",
    "Max Parsons", "Mo Chen", "Mo Li", "Paul Beame", "Peter Pauzauskie",
    "Sara Mouradian", "Scott Dunham", "Serena Eley", "Silas Beane",
    "Stefan Stoll", "Subhadeep Gupta", "Ting Cao", "Xiaodong Xu", "Xiaosong Li"
]
FACULTY.sort()

# ─────────────────────────── Utilities ────────────────────────────────────
_aff_cache: Dict[str, bool] = {}

def _has_uw_affiliation(author_id: str) -> bool:
    if author_id in _aff_cache:
        return _aff_cache[author_id]
    ok = False
    try:
        data = httpx.get(f"https://api.openalex.org/authors/{author_id}", headers=HEADERS, timeout=15).json()
        inst = (data.get("last_known_institution") or {}).get("display_name", "")
        ok = "university of washington" in inst.lower()
    except Exception:
        pass
    _aff_cache[author_id] = ok
    return ok

def _author_in_list(work: Dict, person: str) -> bool:
    cand = person.lower()
    if "authorships" in work:
        names = [a["author"]["display_name"].lower() for a in work["authorships"]]
    else:
        names = [n.lower() for n in work.get("authors", [])]
    return cand in names

def _unique_titles(papers: List[Dict]) -> List[Dict]:
    seen, out = set(), []
    for p in papers:
        t = p.get("display_name", "").lower()
        if t and t not in seen:
            seen.add(t); out.append(p)
    return out

# ─────────────────────────── Collectors ───────────────────────────────────

def collect_openalex(days_back: int) -> List[Dict]:
    since_iso = (_dt.date.today() - _dt.timedelta(days=days_back)).isoformat()
    gathered: Dict[str, Dict] = {}
    for faculty in FACULTY:
        oa_id, _ = openalex_meta(faculty)
        if not oa_id or not _has_uw_affiliation(oa_id):
            continue
        for w in works_openalex(oa_id, since_iso):
            if not _author_in_list(w, faculty):
                continue
            src = ((w.get("primary_location", {}) or {}).get("source", {}) or {}).get("display_name") or \
                  (w.get("host_venue", {}) or {}).get("display_name", "")
            cleaned = {**w, "source": src or ""}
            gathered.setdefault(cleaned.get("doi") or cleaned["id"], cleaned)
    return list(gathered.values())


def collect_arxiv(days_back: int) -> List[Dict]:
    since_date = _dt.date.today() - _dt.timedelta(days=days_back)
    gathered: Dict[str, Dict] = {}
    for faculty in FACULTY:
        for w in works_arxiv(faculty, since_date):
            if _author_in_list(w, faculty):
                gathered.setdefault(w["id"], w)
    return list(gathered.values())

# ─────────────────────────── Formatting ───────────────────────────────────

def _authors_str(p: Dict) -> str:
    names = [a["author"]["display_name"] for a in p.get("authorships", [])] or p.get("authors", [])
    if not names:
        return "Unknown"
    return f"{names[0]} et al." if len(names) > 20 else ", ".join(names)

def _citation(p: Dict) -> str:
    authors = _authors_str(p)
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
    return f"- {cite} [[link]]({url})" if url else f"- {cite}"

# ─────────────────────────── UI ───────────────────────────────────────────
st.set_page_config(page_title="Quantum X Harvester v2", layout="wide")
st.title("Quantum X – On‑demand Paper Lists (strict matching)")

col_oa, col_ax = st.columns(2)

with col_oa:
    d_oa = st.slider("OpenAlex look‑back (days)", 7, 365, 90, 7, key="oa")
    if st.button("Fetch from OpenAlex"):
        with st.spinner("Querying OpenAlex …"):
            papers = _unique_titles(collect_openalex(d_oa))
        st.session_state["papers"] = papers

with col_ax:
    d_ax = st.slider("arXiv look‑back (days)", 7, 365, 90, 7, key="ax")
    if st.button("Fetch from arXiv"):
        with st.spinner("Querying arXiv …"):
            papers = _unique_titles(collect_arxiv(d_ax))
        st.session_state["papers"] = papers

# Display results
if "papers" in st.session_state:
    st.markdown("\n".join(_citation(p) for p in st.session_state["papers"]))
    st.markdown("**Researchers included:** " + ", ".join(FACULTY))
else:
    st.info("Select a window, press a button, and the list will appear here.")
