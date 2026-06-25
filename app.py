import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from rapidfuzz import process, fuzz

# --- Page Config ---
st.set_page_config(page_title="Attendance Tracker", layout="wide")
st.title("📊 Student Attendance Tracker")

# --- Refresh Button ---
if st.button("🔄 Refresh Data"):
    st.cache_data.clear()

# --- Connect to Google Sheets ---
conn = st.connection("gsheets", type=GSheetsConnection)
MASTER_SHEET_URL = "https://docs.google.com/spreadsheets/d/1d3zmUbavKvyo4vns4F9jbzxbdtML7oUnE4eM-WJE8b0/edit"
FORM_SHEET_URL = "https://docs.google.com/spreadsheets/d/1EWwwrPBnLb63aIMAo710SDIQvLFXY_9LSQ9Ke9QeLKM/edit"

@st.cache_data(ttl=60) 
def load_data():
    master_df = conn.read(spreadsheet=MASTER_SHEET_URL) 
    form_df = conn.read(spreadsheet=FORM_SHEET_URL) 
    
    master_df = master_df.dropna(subset=['Student Last Name', 'Student First Name'], how='all')
    form_df = form_df.dropna(subset=['Student Last Name', 'Student First Name'], how='all')
    
    return master_df, form_df

try:
    with st.spinner("Fetching live data from Google Sheets..."):
        df_master, df_form = load_data()

    # Keep original copies for final clean display
    df_master_clean = df_master.copy()
    df_form_clean = df_form.copy()

    # Create working copies for matching
    df_master_match = df_master.copy()
    df_form_match = df_form.copy()

    # --- Data Cleaning (For Matching) ---
    cols_to_match = ['Student Last Name', 'Student First Name', 'Grade Level']
    
    for col in cols_to_match:
        df_master_match[col] = df_master_match[col].astype(str).str.replace(r'\.0$', '', regex=True).str.replace("'", "", regex=False).str.strip().str.lower()
        df_form_match[col] = df_form_match[col].astype(str).str.replace(r'\.0$', '', regex=True).str.replace("'", "", regex=False).str.strip().str.lower()
        if col == 'Grade Level':
            df_master_match[col] = df_master_match[col].str.lstrip('0')
            df_form_match[col] = df_form_match[col].str.lstrip('0')

    # Drop duplicates in the form match tracking
    df_form_match = df_form_match.drop_duplicates(subset=cols_to_match)

    # Add a unique index pointer to map back to original data later
    df_master_match['master_idx'] = df_master_match.index
    df_form_match['form_idx'] = df_form_match.index

    # --- Step 1: Exact Comparison ---
    merged = df_master_match.merge(df_form_match, on=cols_to_match, how='left', indicator=True)
    
    # Separate exact matches from non-exact matches
    exact_matched_master_indices = merged[merged['_merge'] == 'both']['master_idx'].tolist()
    unmatched_merged = merged[merged['_merge'] == 'left_only']
    
    # Get the form indices that have already successfully matched exactly
    used_form_indices = merged[merged['_merge'] == 'both']['form_idx'].tolist()
    # Available form responses left for fuzzy matching
    available_form_pool = df_form_match[~df_form_match['form_idx'].isin(used_form_indices)].copy()

    # --- Step 2: Fuzzy Comparison for Leftovers ---
    potential_matches = []
    truly_missing_master_indices = []

    # Combine names in the available form pool into single strings for full-name matching
    if not available_form_pool.empty:
        available_form_pool['full_name'] = available_form_pool['Student First Name'] + " " + available_form_pool['Student Last Name']
        form_choices = available_form_pool['full_name'].tolist()
        form_idx_map = available_form_pool['form_idx'].tolist()
    else:
        form_choices = []

    for _, row in unmatched_merged.iterrows():
        m_idx = row['master_idx']
        master_full_name = f"{row['Student First Name']} {row['Student Last Name']}"
        
        match_found = False
        if form_choices:
            # Extract the best string match from the form pool
            best_match = process.extractOne(master_full_name, form_choices, scorer=fuzz.token_sort_ratio)
            
            if best_match:
                score = best_match[1]
                match_idx_in_choices = best_match[2]
                corresponding_form_idx = form_idx_map[match_idx_in_choices]
                
                # Threshold: 82% similarity usually catches typos/swapped names without false matching completely wrong people
                if score >= 82:
                    potential_matches.append({
                        'master_idx': m_idx,
                        'form_idx': corresponding_form_idx,
                        'Confidence Score': f"{int(score)}%"
                    })
                    match_found = True
                    # Remove from choices so one form response doesn't match multiple master entries
                    form_choices.pop(match_idx_in_choices)
                    form_idx_map.pop(match_idx_in_choices)

        if not match_found:
            truly_missing_master_indices.append(m_idx)

    # --- Step 3: Build Final DataFrames using Original Clean Data ---
    completed_df = df_master_clean.loc[exact_matched_master_indices]
    
    missing_df = df_master_clean.loc[truly_missing_master_indices]

    # Build the Review panel dataframe
    review_data = []
    for pm in potential_matches:
        m_row = df_master_clean.loc[pm['master_idx']]
        f_row = df_form_clean.loc[pm['form_idx']]
        review_data.append({
            "Roster Name": f"{m_row['Student Last Name']}, {m_row['Student First Name']} (Gr {m_row['Grade Level']})",
            "What They Typed": f"{f_row['Student Last Name']}, {f_row['Student First Name']} (Gr {f_row['Grade Level']})",
            "Match Match Confidence": pm['Confidence Score']
        })
    review_df = pd.DataFrame(review_data)

    # --- Dashboard UI ---
    st.markdown("### Attendance Overview")
    
    # Metrics
    m1, m2, m3 = st.columns(3)
    m1.metric("✅ Confirmed Automatically", len(completed_df))
    m2.metric("⚠️ Needs Quick Review", len(review_df))
    m3.metric("❌ Truly Missing", len(missing_df))
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.success(f"✅ Confirmed Matches ({len(completed_df)})")
        st.dataframe(completed_df, use_container_width=True, hide_index=True)
        
    with col2:
        st.error(f"❌ Missing Students ({len(missing_df)})")
        st.dataframe(missing_df, use_container_width=True, hide_index=True)

    if len(review_df) > 0:
        st.markdown("---")
        st.warning("⚠️ **Potential Matches Found (Check for Typos/Nicknames)**")
        st.info("The students below typed something slightly different than the roster, but the app matched them algorithmically. Verify them here:")
        st.dataframe(review_df, use_container_width=True, hide_index=True)

except Exception as e:
    st.error("An error occurred processing the data layout.")
    st.exception(e)
