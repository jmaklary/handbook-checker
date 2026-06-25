import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd

# --- Page Config ---
st.set_page_config(page_title="Attendance Tracker", layout="wide")
st.title("📊 Student Attendance Tracker")

# --- Connect to Google Sheets ---
# The connection uses the credentials we will store in Streamlit Secrets
conn = st.connection("gsheets", type=GSheetsConnection)

# Replace these URLs with the actual URLs of your Google Sheets
MASTER_SHEET_URL = "https://docs.google.com/spreadsheets/d/1d3zmUbavKvyo4vns4F9jbzxbdtML7oUnE4eM-WJE8b0/edit"
FORM_SHEET_URL = "https://docs.google.com/spreadsheets/d/1EWwwrPBnLb63aIMAo710SDIQvLFXY_9LSQ9Ke9QeLKM/edit"

@st.cache_data(ttl=60) # Caches data for 60 seconds to avoid hitting API limits
def load_data():
    # Read the sheets into Pandas DataFrames
    master_df = conn.read(spreadsheet=MASTER_SHEET_URL) # Adjust usecols if needed
    form_df = conn.read(spreadsheet=FORM_SHEET_URL) 
    return master_df, form_df

try:
    with st.spinner("Fetching live data from Google Sheets..."):
        df_master, df_form = load_data()

    # --- Data Cleaning ---
    # Strip whitespace and convert to lowercase to ensure accurate matching
    cols_to_match = ['Student Last Name', 'Student First Name', 'Grade Level']
    
    for col in cols_to_match:
        df_master[col] = df_master[col].astype(str).str.strip().str.lower()
        df_form[col] = df_form[col].astype(str).str.strip().str.lower()

    # Drop duplicates in the form (in case a student submitted twice)
    df_form = df_form.drop_duplicates(subset=cols_to_match)

    # --- Comparison Logic ---
    # Merge the two dataframes to see who is in both, and who is only in the master
    merged = df_master.merge(df_form, on=cols_to_match, how='left', indicator=True)
    
    # Filter based on the merge indicator
    completed_df = merged[merged['_merge'] == 'both'].drop(columns=['_merge'])
    missing_df = merged[merged['_merge'] == 'left_only'].drop(columns=['_merge'])

    # Format names back to Title Case for nice display
    for col in ['Student Last Name', 'Student First Name']:
        completed_df[col] = completed_df[col].str.title()
        missing_df[col] = missing_df[col].str.title()

    # --- Dashboard UI ---
    st.markdown("### Attendance Overview")
    col1, col2 = st.columns(2)
    
    with col1:
        st.success(f"✅ Submitted: {len(completed_df)}")
        st.dataframe(completed_df, use_container_width=True)
        
    with col2:
        st.error(f"❌ Missing: {len(missing_df)}")
        st.dataframe(missing_df, use_container_width=True)

except Exception as e:
    st.error("Error loading data. Please check your Google Sheet URLs and permissions.")
    st.write(e)

if st.button("🔄 Refresh Data"):
    st.cache_data.clear()
