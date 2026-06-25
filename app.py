import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd

# --- Page Config ---
st.set_page_config(page_title="Attendance Tracker", layout="wide")
st.title("📊 Student Attendance Tracker")

# --- Refresh Button (Must be at the top!) ---
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
    
    # Drop completely empty rows from both sheets right away
    master_df = master_df.dropna(subset=['Student Last Name', 'Student First Name'], how='all')
    form_df = form_df.dropna(subset=['Student Last Name', 'Student First Name'], how='all')
    
    return master_df, form_df

try:
    with st.spinner("Fetching live data from Google Sheets..."):
        df_master, df_form = load_data()

    # Create a COPY of the cached data so Streamlit doesn't glitch
    df_master = df_master.copy()
    df_form = df_form.copy()

    # --- Data Cleaning ---
    cols_to_match = ['Student Last Name', 'Student First Name', 'Grade Level']
    
    for col in cols_to_match:
        # Convert to string, remove '.0', remove apostrophes, strip spaces, and lowercase
        df_master[col] = df_master[col].astype(str).str.replace(r'\.0$', '', regex=True).str.replace("'", "", regex=False).str.strip().str.lower()
        df_form[col] = df_form[col].astype(str).str.replace(r'\.0$', '', regex=True).str.replace("'", "", regex=False).str.strip().str.lower()

    # Drop duplicates in the form (in case a student submitted twice!)
    df_form = df_form.drop_duplicates(subset=cols_to_match)

    # --- Comparison Logic ---
    merged = df_master.merge(df_form, on=cols_to_match, how='left', indicator=True)
    
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
