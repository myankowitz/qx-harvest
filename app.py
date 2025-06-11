import streamlit as st
import pandas as pd
from qx_harvest import collect_papers, bibtex_entry

# ── NEW: page config + instant UI feedback ───────────────────────────────
st.set_page_config(page_title="Quantum X Paper Harvester", layout="wide")
st.title("Quantum X Paper Harvester")

# This line makes sure users see content immediately,
# even before they press the button.
st.info("Adjust the slider, then click **Fetch papers**")
# ─────────────────────────────────────────────────────────────────────────

# ---------- Controls -------------------------------------------------------
DAYS_DEFAULT = 90

days = st.slider(
    "Look-back window (days)",
    min_value=7,
    max_value=365,
    value=DAYS_DEFAULT,
    step=7,
    help="How far back to search for new papers."
)


# ---------- Action button --------------------------------------------------
if st.button("Fetch papers"):
    try:
        with st.spinner("Collecting papers …"):
            papers = collect_papers(days)
    except Exception as exc:
        st.error(f"⚠️ An error occurred: {exc}")
        st.stop()

    if not papers:
        st.warning("No papers found in the selected window.")
        st.stop()

    # ---------- Display results -------------------------------------------
    st.success(f"Found {len(papers)} papers")

    # Text list (always shown)
    md_lines = [
        f"- **{p['display_name']}** ({p['publication_date']})"
        for p in sorted(papers, key=lambda x: x['publication_date'], reverse=True)
    ]
    st.markdown("\n".join(md_lines))

    # Optional table view for power users
    if st.checkbox("Show details table"):
        df = pd.DataFrame(papers)[
            ["display_name", "publication_date", "source", "doi"]
        ].rename(
            columns={
                "display_name": "Title",
                "publication_date": "Date",
                "source": "Journal/Source",
                "doi": "DOI",
            }
        )
        st.dataframe(df, use_container_width=True, hide_index=True)

    # ---------- Downloads --------------------------------------------------
    bib_content = "\n\n".join(bibtex_entry(p) for p in papers)
    md_content = "# Quantum X – new papers\n\n" + "\n".join(md_lines)

    col1, col2 = st.columns(2)
    with col1:
        st.download_button(
            "Download BibTeX",
            bib_content,
            file_name="digest.bib",
            mime="text/plain",
        )
    with col2:
        st.download_button(
            "Download Markdown",
            md_content,
            file_name="digest.md",
            mime="text/markdown",
        )

else:
    st.info(
        f"Press **Fetch papers** to generate a list covering the last {DAYS_DEFAULT} "
        "days, or adjust the slider first."
    )
