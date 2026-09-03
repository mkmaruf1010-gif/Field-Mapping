import streamlit as st
import pandas as pd
import ee
import json
import requests
import gspread
from datetime import datetime
from google.oauth2.service_account import Credentials
from streamlit_js_eval import get_geolocation

st.set_page_config(page_title="Multi-User GIS Field Data Collector", layout="wide")

# --- ১. গুগল আর্থ ইঞ্জিন অথেন্টিকেশন ---
@st.cache_resource
def init_earth_engine():
    try:
        credentials_dict = dict(st.secrets["gee_credentials"])
        
        credentials = ee.ServiceAccountCredentials(
            credentials_dict["client_email"],
            key_data=json.dumps(credentials_dict)
        )
        ee.Initialize(credentials)
        return True
    except Exception as e:
        st.error(f"GEE Auth Error: {e}")
        return False

gee_active = init_earth_engine()

# --- ২. গুগল শিটস কানেকশন ---
@st.cache_resource
def connect_to_gsheet_client():
    try:
        scope = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        credentials_dict = dict(st.secrets["gee_credentials"])
        creds = Credentials.from_service_account_info(credentials_dict, scopes=scope)
        client = gspread.authorize(creds)
        
        spreadsheet = client.open("FieldSurvey")
        return spreadsheet
    except Exception as e:
        st.error(f"Google Sheet Connection Error: {e}")
        return None

gsheet_spreadsheet = connect_to_gsheet_client()

# ডাটা সেভ করার জন্য ১ম ট্যাব (index 0)
gsheet = gsheet_spreadsheet.sheet1 if gsheet_spreadsheet else None

# --- ৩. ৩য় ট্যাব (Index 2) থেকে সার্ভেয়ার নামের তালিকা পড়ার ফাংশন ---
@st.cache_data(ttl= 5)
def get_surveyor_list():
    try:
        if gsheet_spreadsheet:
            # ৩য় ট্যাব থেকে নাম রিড করা
            surveyor_tab = gsheet_spreadsheet.get_worksheet(1)
            names = surveyor_tab.col_values(1)[1:]
            
            valid_names = [name.strip() for name in names if name.strip()]
            if valid_names:
                return valid_names
    except Exception as e:
        st.warning(f"৩য় ট্যাব থেকে সার্ভেয়ার নাম পড়তে সমস্যা হয়েছে: {e}")
    
    return ["Surveyor_1", "Surveyor_2", "Surveyor_3"]

# --- ৪. ২য় ট্যাব (Index 1) থেকে Feature Type পড়ার ফাংশন ---
@st.cache_data(ttl= 5)
def get_feature_types():
    try:
        if gsheet_spreadsheet:
            # ২য় ট্যাব থেকে ফিচার রিড করা
            feature_tab = gsheet_spreadsheet.get_worksheet(2)
            features = feature_tab.col_values(1)[1:]
            
            valid_features = [f.strip() for f in features if f.strip()]
            if valid_features:
                return valid_features
    except Exception as e:
        st.warning(f"২য় ট্যাব থেকে Feature Type পড়তে সমস্যা হয়েছে: {e}")
    
    return ["Point of Interest", "Water Body", "Road Node", "Boundary Point"]

# --- ৫. এলিভেশন ফেচিং ফাংশন (১০ দশমিক স্থান সাপোর্ট) ---
def get_elevation(lat, lon):
    if gee_active:
        try:
            point = ee.Geometry.Point([lon, lat])
            dem = ee.Image('USGS/SRTM30M')
            elevation_data = dem.reduceRegion(
                reducer=ee.Reducer.first(),
                geometry=point,
                scale=30
            ).getInfo()
            
            val = elevation_data.get('elevation')
            if val is not None:
                return round(float(val), 10)
        except Exception:
            pass

    # Open-Elevation REST API
    try:
        url = f"https://api.open-elevation.com/api/v1/lookup?locations={lat:.001f},{lon:.001f}"
        response = requests.get(url, timeout=5).json()
        return round(float(response['results'][0]['elevation']), 10)
    except Exception:
        return "N/A"

# --- ৬. ইউজার ইন্টারফেস (UI) ---
st.title(" Mass GIS Field GPS & Elevation Data Collector")
st.caption("Multi-User Live Geolocation")

col1, col2 = st.columns(2)
with col1:
    # ৩য় ট্যাব থেকে নাম লোড হবে
    surveyor_options = get_surveyor_list()
    surveyor_name = st.selectbox("Select Surveyor Name / ID", surveyor_options)
    
with col2:
    # ২য় ট্যাব থেকে ফিচার লোড হবে
    feature_options = get_feature_types()
    feature_type = st.selectbox("Select Feature Type", feature_options)

st.markdown("---")

# --- ৭. লাইভ জিপিএস ক্যাপচার ---
st.subheader("Live Coordinate Capture")
loc = get_geolocation()

if loc and 'coords' in loc:
    lat = float(loc['coords']['latitude'])
    lon = float(loc['coords']['longitude'])
    accuracy = loc['coords']['accuracy']

    st.markdown(
        f"<div style='padding: 12px; background-color: #d4edda; color: #155724; border-radius: 5px;'>"
        f"<b>GPS Location Fetched!</b><br>"
        f"<b>Latitude:</b> {lat:.0010f}<br>"
        f"<b>Longitude:</b> {lon:.0010f}<br>"
        f"<b>Accuracy:</b> ±{accuracy:.01f}m"
        f"</div>", 
        unsafe_allow_html=True
    )

    # --- ৮. পয়েন্ট সেভ ও গুগল শিট সিঙ্ক ---
    if st.button("Capture Coordinate"):
        elevation = get_elevation(lat, lon)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        if gsheet:
            try:
                existing_rows = len(gsheet.get_all_values())
                point_id = existing_rows
                
                row_data = [
                    point_id,
                    surveyor_name,
                    feature_type,
                    f"{lat:.0010f}",
                    f"{lon:.0010f}",
                    str(elevation),
                    round(accuracy, 2),
                    timestamp
                ]
                
                gsheet.append_row(row_data)
                st.toast(f"Point #{point_id} Google Sheet-এ সিঙ্ক হয়েছে!")
            except Exception as e:
                st.error(f"Data Sync Failed: {e}")
        else:
            st.error("Google Sheet কানেক্ট করা নেই। secrets.toml চেক করুন।")

else:
    st.warning(" Please 'Allow' Location Permission on your browser and enable device GPS.")

# --- ৯. রিয়েল-টাইম সেন্ট্রাল গুগল শিট ড্যাশবোর্ড ---
st.markdown("---")
st.subheader(" Data View")

if gsheet:
    try:
        records = gsheet.get_all_records()
        if records:
            df_all = pd.DataFrame(records)
            
            unique_surveyors = ["All Surveyors"] + list(df_all["Surveyor"].unique())
            selected_surveyor = st.selectbox(" Filter by Surveyor:", unique_surveyors)
            
            if selected_surveyor != "All Surveyors":
                filtered_df = df_all[df_all["Surveyor"] == selected_surveyor]
            else:
                filtered_df = df_all
                
            st.dataframe(filtered_df, use_container_width=True)
            st.caption(f"Showing {len(filtered_df)} points (Total Recorded: {len(df_all)})")
            
            @st.cache_data
            def convert_df_to_excel(dataframe):
                from io import BytesIO
                output = BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    dataframe.to_excel(writer, index=False, sheet_name='GIS_Survey')
                return output.getvalue()

            excel_data = convert_df_to_excel(filtered_df)

            st.download_button(
                label=" Export Current View to Excel (.xlsx)",
                data=excel_data,
                file_name=f"GIS_Survey_{selected_surveyor}_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        else:
            st.info("No Data")
    except Exception as e:
        st.error(f"Error loading table: {e}")
