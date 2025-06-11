# app.py  ── lives in the repo root
import io, pandas as pd, streamlit as st
from qx_harvest import collect_papers, bibtex_entry  # import from your script

st.set_page_config(page_title="Quantum X Paper Harvester", layout="wide")
st.title("Quantum X Paper Harvester")

days = st.slider("Look-back window (days)", 7, 365, 90, 7)

if st.button("Fetch papers"):
    with st.spinner("Collecting …"):
        papers = collect_papers(days)

    # nice table view
    df = pd.DataFrame(papers)[["display_name", "publication_date", "source", "doi"]]
    st.success(f"Found {len(df)} unique papers")
    st.dataframe(df, use_container_width=True, hide_index=True)

    # build downloads in-memory
    md = "# Quantum X new papers\\n\\n" + "\\n".join(
        f"- **{p['display_name']}** ({p['publication_date']})" for p in papers)
    bib = "\\n\\n".join(bibtex_entry(p) for p in papers)

    st.download_button("Download BibTeX", bib, "digest.bib", "text/plain")
    st.download_button("Download Markdown", md, "digest.md", "text/markdown")
