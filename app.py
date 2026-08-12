import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from rapidfuzz import process, fuzz

# --- Session State Memory ---
if "manual_matches" not in st.session_state:
    st.session_state.manual_matches = set()

# --- Page Config ---
st.set_page_config(page_title="SLCS Handbook Checker", layout="wide")
st.title("📚 SLCS Handbook Checker")

# --- Refresh Control ---
if st.button("🔄 Refresh Data", use_container_width=True):
    st.cache_data.clear()

# --- Connect to Google Sheets ---
conn = st.connection("gsheets", type=GSheetsConnection)
MASTER_SHEET_URL = "https://docs.google.com/spreadsheets/d/1d3zmUbavKvyo4vns4F9jbzxbdtML7oUnE4eM-WJE8b0/edit"
FORM_SHEET_URL = "https://docs.google.com/spreadsheets/d/1EWwwrPBnLb63aIMAo710SDIQvLFXY_9LSQ9Ke9QeLKM/edit"

@st.cache_data(ttl=60) 
def load_data():
    master_df = conn.read(spreadsheet=MASTER_SHEET_URL) 
    form_df = conn.read(spreadsheet=FORM_SHEET_URL) 
    
    try:
        approved_df = conn.read(spreadsheet=MASTER_SHEET_URL, worksheet="Approved Matches")
    except Exception:
        approved_df = pd.DataFrame(columns=['Student Last Name', 'Student First Name', 'Grade Level'])
        
    try:
        ignored_df = conn.read(spreadsheet=MASTER_SHEET_URL, worksheet="Ignored Submissions")
    except Exception:
        ignored_df = pd.DataFrame(columns=['Student Last Name', 'Student First Name', 'Grade Level'])

    master_df = master_df.dropna(subset=['Student Last Name', 'Student First Name'], how='all')
    form_df = form_df.dropna(subset=['Student Last Name', 'Student First Name'], how='all')
    approved_df = approved_df.dropna(subset=['Student Last Name', 'Student First Name'], how='all')
    ignored_df = ignored_df.dropna(subset=['Student Last Name', 'Student First Name'], how='all')
    
    return master_df, form_df, approved_df, ignored_df

def is_non_agreement(val):
    v = str(val).strip().lower()
    if v in ['no', 'n', 'no agreement', 'do not agree', 'i do not agree', 'disagree', 'not agreed']:
        return True
    if any(phrase in v for phrase in ['do not agree', 'i do not agree', 'disagree', 'no agreement', 'not agree', 'opt out']):
        return True
    if v.startswith('no -') or v.startswith('no,') or v.startswith('no '):
        return True
    return False

try:
    with st.spinner("Fetching live data from Google Sheets..."):
        df_master, df_form, df_approved, df_ignored = load_data()

    df_master_clean = df_master.copy()
    df_form_clean = df_form.copy()

    df_master_match = df_master.copy()
    df_form_match = df_form.copy()
    
    df_approved_match = df_approved.copy() if not df_approved.empty else pd.DataFrame(columns=['Student Last Name', 'Student First Name', 'Grade Level'])
    df_ignored_match = df_ignored.copy() if not df_ignored.empty else pd.DataFrame(columns=['Student Last Name', 'Student First Name', 'Grade Level'])

    # --- Data Cleaning ---
    cols_to_match = ['Student Last Name', 'Student First Name', 'Grade Level']
    for col in cols_to_match:
        df_master_match[col] = df_master_match[col].astype(str).str.replace(r'\.0$', '', regex=True).str.replace("'", "", regex=False).str.strip().str.lower()
        df_form_match[col] = df_form_match[col].astype(str).str.replace(r'\.0$', '', regex=True).str.replace("'", "", regex=False).str.strip().str.lower()
        
        if not df_approved_match.empty and col in df_approved_match.columns:
            df_approved_match[col] = df_approved_match[col].astype(str).str.replace(r'\.0$', '', regex=True).str.replace("'", "", regex=False).str.strip().str.lower()
            
        if not df_ignored_match.empty and col in df_ignored_match.columns:
            df_ignored_match[col] = df_ignored_match[col].astype(str).str.replace(r'\.0$', '', regex=True).str.replace("'", "", regex=False).str.strip().str.lower()
        
        if col == 'Grade Level':
            df_master_match[col] = df_master_match[col].str.lstrip('0')
            df_form_match[col] = df_form_match[col].str.lstrip('0')
            if not df_approved_match.empty and col in df_approved_match.columns:
                df_approved_match[col] = df_approved_match[col].str.lstrip('0')
            if not df_ignored_match.empty and col in df_ignored_match.columns:
                df_ignored_match[col] = df_ignored_match[col].str.lstrip('0')

    # Assign IDs to track original rows
    df_master_match['master_idx'] = df_master_match.index
    df_form_match['form_idx'] = df_form_match.index

    # --- Filter out Ignored Submissions ---
    if not df_ignored_match.empty:
        ignored_merge = df_form_match.merge(df_ignored_match, on=cols_to_match, how='left', indicator=True)
        valid_form_indices = ignored_merge[ignored_merge['_merge'] == 'left_only']['form_idx'].tolist()
        df_form_match = df_form_match[df_form_match['form_idx'].isin(valid_form_indices)]
        df_form_clean = df_form_clean.loc[valid_form_indices]

    df_form_match = df_form_match.drop_duplicates(subset=cols_to_match)

    # --- Step 1: Exact Comparison & Permanent Approvals ---
    merged = df_master_match.merge(df_form_match, on=cols_to_match, how='left', indicator=True)
    
    exact_matched_master_indices = merged[merged['_merge'] == 'both']['master_idx'].tolist()
    used_form_indices = merged[merged['_merge'] == 'both']['form_idx'].tolist()

    if not df_approved_match.empty:
        approved_merged = df_master_match.merge(df_approved_match, on=cols_to_match, how='inner')
        for idx in approved_merged['master_idx'].tolist():
            if idx not in exact_matched_master_indices:
                exact_matched_master_indices.append(idx)

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
        form_idx_map = []

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

    # --- Step 2.5: Catch the Orphaned Form Submissions ---
    orphaned_form_indices = form_idx_map 

    # --- Step 3: Compile Final Categories ---
    completed_df = df_master_clean.loc[exact_matched_master_indices].copy()
    missing_df = df_master_clean.loc[truly_missing_master_indices].copy()
    orphaned_df = df_form_clean.loc[orphaned_form_indices].copy()

    for col in ['Student Last Name', 'Student First Name']:
        completed_df[col] = completed_df[col].astype(str).str.title()
        missing_df[col] = missing_df[col].astype(str).str.title()
        if not orphaned_df.empty:
            orphaned_df[col] = orphaned_df[col].astype(str).str.title()

    # Sort the missing students by Last Name, then First Name
    missing_df = missing_df.sort_values(by=['Student Last Name', 'Student First Name'])

    # Build Batch Options for orphans
    batch_options = ["-- Select Action --", "🗑️ Dismiss (Duplicate)"]
    missing_mapping = {}
    
    for m_idx, row in missing_df.iterrows():
        display_name = f"{row['Student Last Name']}, {row['Student First Name']} (Gr {row['Grade Level']})"
        batch_options.append(display_name)
        missing_mapping[display_name] = m_idx

    # --- Step 4: Check Agreement Columns for "No" ---
    ignore_cols = ['Student Last Name', 'Student First Name', 'Grade Level', 'Timestamp', 'form_idx', 'master_idx']
    question_cols = [c for c in df_form_clean.columns if c not in ignore_cols]
    
    flagged_students = []
    for _, row in df_form_clean.iterrows():
        reasons = []
        for q_col in question_cols:
            answer = str(row[q_col]).strip()
            if is_non_agreement(answer):
                reasons.append(f"**{q_col}**: {answer}")
        
        if reasons:
            flagged_students.append({
                "Student Name": f"{str(row['Student Last Name']).title()}, {str(row['Student First Name']).title()}",
                "Grade Level": row['Grade Level'],
                "Flagged Responses": "  |  ".join(reasons)
            })
    df_flagged = pd.DataFrame(flagged_students)

    review_rows_data = []
    for pm in potential_matches:
        m_row = df_master_clean.loc[pm['master_idx']]
        f_row = df_form_clean.loc[pm['form_idx']]
        review_rows_data.append({
            "master_idx": pm['master_idx'],
            "form_idx": pm['form_idx'],
            "Roster Name": f"{m_row['Student Last Name'].title()}, {m_row['Student First Name'].title()} (Gr {m_row['Grade Level']})",
            "What They Typed": f"{f_row['Student Last Name'].title()}, {f_row['Student First Name'].title()} (Gr {f_row['Grade Level']})",
            "Confidence Score": pm['Confidence Score'],
            "m_last": m_row['Student Last Name'],
            "m_first": m_row['Student First Name'],
            "m_grade": m_row['Grade Level']
        })

    # --- Dashboard UI Layout ---
    st.markdown("### Submission Overview")
    
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("✅ Confirmed Matches", len(completed_df))
    m2.metric("⚠️ Quick Review", len(review_rows_data))
    m3.metric("❓ Unmatched Submissions", len(orphaned_df))
    m4.metric("❌ Truly Missing", len(missing_df))
    m5.metric("🚨 Action Required", len(df_flagged))
    
    col1, col2 = st.columns(2)
    with col1:
        st.success(f"✅ Confirmed Matches ({len(completed_df)})")
        st.dataframe(completed_df, use_container_width=True, hide_index=True)
        
    with col2:
        st.error(f"❌ Missing Students ({len(missing_df)})")
        
        # Add checkbox column for manual overrides
        missing_display = missing_df.copy()
        missing_display.insert(0, "Force Confirm", False)
        
        # Interactive dataframe with checkboxes
        edited_missing = st.data_editor(
            missing_display,
            hide_index=True,
            use_container_width=True,
            disabled=["Student Last Name", "Student First Name", "Grade Level"],
            column_config={
                "Force Confirm": st.column_config.CheckboxColumn(
                    "Confirm?", 
                    help="Check to manually mark this student as confirmed (e.g. paper forms)",
                    default=False
                )
            },
            key="missing_students_editor"
        )
        
        # Process checked students
        if st.button("✅ Force Confirm Selected Students", use_container_width=True):
            selected_rows = edited_missing[edited_missing["Force Confirm"] == True]
            
            if not selected_rows.empty:
                new_approvals = []
                for _, row in selected_rows.iterrows():
                    new_approvals.append({
                        'Student Last Name': row['Student Last Name'],
                        'Student First Name': row['Student First Name'],
                        'Grade Level': row['Grade Level']
                    })
                
                updated_approved = pd.concat([df_approved, pd.DataFrame(new_approvals)], ignore_index=True)
                conn.update(spreadsheet=MASTER_SHEET_URL, worksheet="Approved Matches", data=updated_approved)
                st.cache_data.clear()
                st.rerun()
            else:
                st.warning("Please check at least one student before clicking confirm.")

    # --- Action Required Section ---
    if len(df_flagged) > 0:
        st.markdown("---")
        st.error("🚨 **Action Required: Students Who Checked 'No' / Disagreed**")
        st.dataframe(df_flagged, use_container_width=True, hide_index=True)

    # --- Unmatched Form Responses (BATCH PROCESS) ---
    if len(orphaned_df) > 0:
        st.markdown("---")
        st.warning("❓ **Unmatched Form Submissions (Batch Processing)**")
        st.info("Select the correct action for each orphaned submission below. When you're ready, click 'Process Selected Actions' to update them all at once.")
        
        for f_idx, f_row in orphaned_df.iterrows():
            c1, c2 = st.columns([1, 1])
            
            form_text = f"{f_row['Student Last Name']}, {f_row['Student First Name']} (Gr {f_row['Grade Level']})"
            c1.write(f"**Submitted:** {form_text}")
            
            # Using session state key to track the selection
            st.selectbox(
                "Action:", 
                options=batch_options, 
                key=f"batch_select_{f_idx}",
                label_visibility="collapsed"
            )
            st.markdown("<hr style='margin: 0; padding: 0; border: none; border-bottom: 1px dashed #ddd;'>", unsafe_allow_html=True)
        
        st.write("") # Quick spacing
        
        # Batch Process Button
        if st.button("🚀 Process Selected Actions", use_container_width=True, type="primary"):
            new_approved_records = []
            new_ignored_records = []
            
            for f_idx, f_row in orphaned_df.iterrows():
                selection = st.session_state.get(f"batch_select_{f_idx}", "-- Select Action --")
                
                if selection == "🗑️ Dismiss (Duplicate)":
                    new_ignored_records.append({
                        'Student Last Name': f_row['Student Last Name'],
                        'Student First Name': f_row['Student First Name'],
                        'Grade Level': f_row['Grade Level']
                    })
                elif selection != "-- Select Action --":
                    # It's a student match
                    m_idx = missing_mapping[selection]
                    m_row = df_master_clean.loc[m_idx]
                    
                    new_approved_records.append({
                        'Student Last Name': m_row['Student Last Name'],
                        'Student First Name': m_row['Student First Name'],
                        'Grade Level': m_row['Grade Level']
                    })
            
            # Write to Google Sheets if there are updates
            updates_made = False
            
            if new_approved_records:
                updated_approved = pd.concat([df_approved, pd.DataFrame(new_approved_records)], ignore_index=True)
                conn.update(spreadsheet=MASTER_SHEET_URL, worksheet="Approved Matches", data=updated_approved)
                updates_made = True
                
            if new_ignored_records:
                updated_ignored = pd.concat([df_ignored, pd.DataFrame(new_ignored_records)], ignore_index=True)
                conn.update(spreadsheet=MASTER_SHEET_URL, worksheet="Ignored Submissions", data=updated_ignored)
                updates_made = True
                
            if updates_made:
                st.cache_data.clear()
                st.rerun()
            else:
                st.warning("No actions were selected to process.")

    # --- Interactive Review Component (Fuzzy Matches) ---
    if len(review_rows_data) > 0:
        st.markdown("---")
        st.warning("⚠️ **Potential Matches Found (Check for Typos/Nicknames)**")
        st.info("Click **✅ Approve Match** to permanently verify a student across all sessions:")
        
        h1, h2, h3, h4 = st.columns([3.5, 3.5, 1.5, 1.5])
        h1.markdown("**Roster Identity**")
        h2.markdown("**What Student Entered**")
        h3.markdown("**Similarity Score**")
        h4.markdown("**Action**")
        st.markdown("<hr style='margin:0px 0px 10px 0px;'>", unsafe_allow_html=True)
        
        for item in review_rows_data:
            c1, c2, c3, c4 = st.columns([3.5, 3.5, 1.5, 1.5])
            c1.write(item["Roster Name"])
            c2.write(item["What They Typed"])
            c3.write(item["Confidence Score"])
            with c4:
                if st.button("✅ Approve Match", key=f"btn_{item['master_idx']}_{item['form_idx']}", use_container_width=True):
                    new_entry = pd.DataFrame([{
                        'Student Last Name': item['m_last'],
                        'Student First Name': item['m_first'],
                        'Grade Level': item['m_grade']
                    }])
                    updated_approved = pd.concat([df_approved, new_entry], ignore_index=True)
                    conn.update(spreadsheet=MASTER_SHEET_URL, worksheet="Approved Matches", data=updated_approved)
                    st.cache_data.clear()
                    st.rerun()

except Exception as e:
    st.error("An error occurred building the operational layout.")
    st.exception(e)
