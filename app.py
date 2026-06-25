import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from rapidfuzz import process, fuzz

# --- Session State Memory (Must be initialized at the very top) ---
if "manual_matches" not in st.session_state:
    st.session_state.manual_matches = set()

# --- Page Config ---
st.set_page_config(page_title="Attendance Tracker", layout="wide")
st.title("📊 Student Attendance Tracker")

# --- Top Dashboard Controls ---
col_ref, col_reset = st.columns([1, 1])
with col_ref:
    if st.button("🔄 Refresh Data", use_container_width=True):
        st.cache_data.clear()
with col_reset:
    if len(st.session_state.manual_matches) > 0:
        if st.button("🗑️ Reset Manual Overrides", use_container_width=True):
            st.session_state.manual_matches.clear()
            st.rerun()

# --- Connect to Google Sheets ---
conn = st.connection("gsheets", type=GSheetsConnection)
MASTER_SHEET_URL = "https://docs.google.com/spreadsheets/d/1d3zmUbavKvyo4vns4F9jbzxbdtML7oUnE4eM-WJE8b0/edit"
FORM_SHEET_URL = "https://docs.google.com/spreadsheets/d/1EWwwrPBnLb63aIMAo710SDIQvLFXY_9LSQ9Ke9QeLKM/edit"

@st.cache_data(ttl=60) 
def load_data():
    master_df = conn.read(spreadsheet=MASTER_SHEET_URL) 
    form_df = conn.read(spreadsheet=FORM_SHEET_URL) 
    
    # Drop blank rows
    master_df = master_df.dropna(subset=['Student Last Name', 'Student First Name'], how='all')
    form_df = form_df.dropna(subset=['Student Last Name', 'Student First Name'], how='all')
    
    return master_df, form_df

try:
    with st.spinner("Fetching live data from Google Sheets..."):
        df_master, df_form = load_data()

    # Keep original copies for clean display
    df_master_clean = df_master.copy()
    df_form_clean = df_form.copy()

    # Working copies for parsing matching text
    df_master_match = df_master.copy()
    df_form_match = df_form.copy()

    # --- Data Cleaning ---
    cols_to_match = ['Student Last Name', 'Student First Name', 'Grade Level']
    for col in cols_to_match:
        df_master_match[col] = df_master_match[col].astype(str).str.replace(r'\.0$', '', regex=True).str.replace("'", "", regex=False).str.strip().str.lower()
        df_form_match[col] = df_form_match[col].astype(str).str.replace(r'\.0$', '', regex=True).str.replace("'", "", regex=False).str.strip().str.lower()
        if col == 'Grade Level':
            df_master_match[col] = df_master_match[col].str.lstrip('0')
            df_form_match[col] = df_form_match[col].str.lstrip('0')

    # Remove submission duplicates 
    df_form_match = df_form_match.drop_duplicates(subset=cols_to_match)

    # Attach tracker integers so we can bind elements to actions
    df_master_match['master_idx'] = df_master_match.index
    df_form_match['form_idx'] = df_form_match.index

    # --- Step 1: Exact Comparison & Intercept Manual Approvals ---
    merged = df_master_match.merge(df_form_match, on=cols_to_match, how='left', indicator=True)
    
    exact_matched_master_indices = merged[merged['_merge'] == 'both']['master_idx'].tolist()
    used_form_indices = merged[merged['_merge'] == 'both']['form_idx'].tolist()
    
    # Inject your manually clicked overrides into the confirmed pool
    for m_idx, f_idx in list(st.session_state.manual_matches):
        if m_idx in df_master_match.index and f_idx in df_form_match.index:
            if m_idx not in exact_matched_master_indices:
                exact_matched_master_indices.append(m_idx)
            if f_idx not in used_form_indices:
                used_form_indices.append(f_idx)

    # Isolate unsubmitted entries, dropping anyone who was manually cleared
    unmatched_merged = merged[(merged['_merge'] == 'left_only') & (~merged['master_idx'].isin(exact_matched_master_indices))]
    available_form_pool = df_form_match[~df_form_match['form_idx'].isin(used_form_indices)].copy()

    # --- Step 2: Algorithmic Fuzzy Matching for Leftovers ---
    potential_matches = []
    truly_missing_master_indices = []

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
            best_match = process.extractOne(master_full_name, form_choices, scorer=fuzz.token_sort_ratio)
            
            if best_match:
                score = best_match[1]
                match_idx_in_choices = best_match[2]
                corresponding_form_idx = form_idx_map[match_idx_in_choices]
                
                if score >= 82:
                    potential_matches.append({
                        'master_idx': m_idx,
                        'form_idx': corresponding_form_idx,
                        'Confidence Score': f"{int(score)}%"
                    })
                    match_found = True
                    form_choices.pop(match_idx_in_choices)
                    form_idx_map.pop(match_idx_in_choices)

        if not match_found:
            truly_missing_master_indices.append(m_idx)

    # --- Step 3: Compile Final Categories Using Original Formats ---
    completed_df = df_master_clean.loc[exact_matched_master_indices].copy()
    missing_df = df_master_clean.loc[truly_missing_master_indices].copy()

    # Title-case for a professional clean layout
    for col in ['Student Last Name', 'Student First Name']:
        completed_df[col] = completed_df[col].astype(str).str.title()
        missing_df[col] = missing_df[col].astype(str).str.title()

    # Gather data elements specifically to construct the Review Layout
    review_rows_data = []
    for pm in potential_matches:
        m_row = df_master_clean.loc[pm['master_idx']]
        f_row = df_form_clean.loc[pm['form_idx']]
        review_rows_data.append({
            "master_idx": pm['master_idx'],
            "form_idx": pm['form_idx'],
            "Roster Name": f"{m_row['Student Last Name'].title()}, {m_row['Student First Name'].title()} (Gr {m_row['Grade Level']})",
            "What They Typed": f"{f_row['Student Last Name'].title()}, {f_row['Student First Name'].title()} (Gr {f_row['Grade Level']})",
            "Confidence Score": pm['Confidence Score']
        })

    # --- Dashboard UI Layout ---
    st.markdown("### Attendance Overview")
    
    m1, m2, m3 = st.columns(3)
    m1.metric("✅ Confirmed Matches", len(completed_df))
    m2.metric("⚠️ Needs Quick Review", len(review_rows_data))
    m3.metric("❌ Truly Missing", len(missing_df))
    
    col1, col2 = st.columns(2)
    with col1:
        st.success(f"✅ Confirmed Matches ({len(completed_df)})")
        st.dataframe(completed_df, use_container_width=True, hide_index=True)
    with col2:
        st.error(f"❌ Missing Students ({len(missing_df)})")
        st.dataframe(missing_df, use_container_width=True, hide_index=True)

    # --- Interactive Review Component ---
    if len(review_rows_data) > 0:
        st.markdown("---")
        st.warning("⚠️ **Potential Matches Found (Check for Typos/Nicknames)**")
        st.info("The students below submitted data with typos or mismatched fields. Click **✅ Approve Match** to manually verify them:")
        
        # Formulate a custom grid header
        h1, h2, h3, h4 = st.columns([3.5, 3.5, 1.5, 1.5])
        h1.markdown("**Roster Identity**")
        h2.markdown("**What Student Entered**")
        h3.markdown("**Similarity Score**")
        h4.markdown("**Action**")
        st.markdown("<hr style='margin:0px 0px 10px 0px;'>", unsafe_allow_html=True)
        
        # Build individual action rows
        for item in review_rows_data:
            c1, c2, c3, c4 = st.columns([3.5, 3.5, 1.5, 1.5])
            c1.write(item["Roster Name"])
            c2.write(item["What They Typed"])
            c3.write(item["Confidence Score"])
            with c4:
                # Every button receives a unique identifier string using their index combinations
                if st.button("✅ Approve Match", key=f"btn_{item['master_idx']}_{item['form_idx']}", use_container_width=True):
                    st.session_state.manual_matches.add((item['master_idx'], item['form_idx']))
                    st.rerun()

except Exception as e:
    st.error("An error occurred building the operational layout.")
    st.exception(e)
