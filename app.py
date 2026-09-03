import streamlit as st
import pandas as pd
import ee
import json
import requests
import gspread
from datetime import datetime
from oauth2client.service_account import ServiceAccountCredentials
from streamlit_js_eval import get_geolocation

st.set_page_config(page_title="Multi-User GIS Field Collector", layout="wide")

# --- ১. গুগল আর্থ ইঞ্জিন অথেন্টিকেশন ---
@st.cache_resource
def init_earth_engine():
    try:
        credentials_dict = dict(st.secrets["gee_credentials"])
        credentials = ee.ServiceAccountCredentials(
            credentials_dict["client_email"],
            key_data=credentials_dict
        )
        ee.Initialize(credentials)
        return True
    except Exception as e:
        st.error(f"GEE Auth Error: {e}")
        return False

gee_active = init_earth_engine()

# --- ২. গুগল শিটস কানেকশন ---
@st.cache_resource
def connect_to_gsheet():
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        credentials_dict = dict(st.secrets["gee_credentials"])
        creds = ServiceAccountCredentials.from_json_keyfile_dict(credentials_dict, scope)
        client = gspread.authorize(creds)
        # আপনার তৈরি করা Google Sheet-এর নাম দিন
        sheet = client.open("GIS_Field_Survey_Data").sheet1
        return sheet
    except Exception as e:
        st.error(f"Google Sheet Connection Error: {e}")
        return None

gsheet = connect_to_gsheet()

# --- ৩. এলিভেশন ফেচিং ফাংশন (১০ দশমিক ঘর সাপোর্টসহ) ---
def get_elevation(lat, lon):
    # ১ম চেষ্টা: Google Earth Engine (SRTM 30m)
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

    # ২য় চেষ্টা (Fallback): Open-Elevation REST API
    try:
        url = f"https://api.open-elevation.com/api/v1/lookup?locations={lat:.10f},{lon:.10f}"
        response = requests.get(url, timeout=5).json()
        return round(float(response['results'][0]['elevation']), 10)
    except Exception:
        return "N/A"

# --- ৪. ইউজার ইন্টারফেস (UI) ---
st.title("📍 Smart GIS Field GPS & Elevation Collector")
st.caption("Multi-User Live Geolocation, Google Earth Elevation & Google Sheets Sync")

col1, col2 = st.columns(2)
with col1:
    surveyor_name = st.text_input("Surveyor Name / ID", "Surveyor_1")
with col2:
    feature_type = st.selectbox("Feature Type", ["Point of Interest", "Water Body", "Road Node", "Boundary Point"])

st.markdown("---")

# --- ৫. লাইভ জিপিএস ক্যাপচার ---
st.subheader("Live Coordinate Capture")
loc = get_geolocation()

if loc and 'coords' in loc:
    # ১০ দশমিক ঘর ফ্লোটিং ভ্যালু নিশ্চিত করা
    lat = float(loc['coords']['latitude'])
    lon = float(loc['coords']['longitude'])
    accuracy = loc['coords']['accuracy']

    st.markdown(
        f"<div style='padding: 12px; background-color: #d4edda; color: #155724; border-radius: 5px;'>"
        f"<b>GPS Location Fetched!</b><br>"
        f"<b>Latitude:</b> {lat:.10f}<br>"
        f"<b>Longitude:</b> {lon:.10f}<br>"
        f"<b>Accuracy:</b> ±{accuracy:.1f}m"
        f"</div>", 
        unsafe_allow_html=True
    )

    # --- ৬. পয়েন্ট সেভ ও গুগল শিট পুশ বাটন ---
    if st.button("➕ Capture & Sync to Google Sheet"):
        elevation = get_elevation(lat, lon)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        if gsheet:
            try:
                # গুগল শিটে সারি গণনা করে নতুন ID তৈরি
                existing_rows = len(gsheet.get_all_values())
                point_id = existing_rows # Header বাদ দিয়ে ১ থেকে শুরু
                
                row_data = [
                    point_id,
                    surveyor_name,
                    feature_type,
                    f"{lat:.10f}",
                    f"{lon:.10f}",
                    str(elevation),
                    round(accuracy, 2),
                    timestamp
                ]
                
                # সেন্ট্রাল গুগল শিটে ডাটা পাঠানো
                gsheet.append_row(row_data)
                st.toast(f"Point #{point_id} Google Sheet-এ সিঙ্ক হয়েছে!")
            except Exception as e:
                st.error(f"Data Sync Failed: {e}")
        else:
            st.error("Google Sheet কানেক্ট করা নেই। secrets.toml চেক করুন।")

else:
    st.warning("⚠️ Please 'Allow' Location Permission on your browser and enable device GPS.")

# --- ৭. রিয়েল-টাইম সেন্ট্রাল গুগল শিট ও সার্ভেয়ার ড্যাশবোর্ড ---
st.markdown("---")
st.subheader("📊 Live Central Google Sheet Data")

if gsheet:
    try:
        records = gsheet.get_all_records()
        if records:
            df_all = pd.DataFrame(records)
            
            # সার্ভেয়ার অনুযায়ী ড্রপডাউন ফিল্টার
            unique_surveyors = ["All Surveyors"] + list(df_all["Surveyor"].unique())
            selected_surveyor = st.selectbox("🎯 Filter by Surveyor:", unique_surveyors)
            
            if selected_surveyor != "All Surveyors":
                filtered_df = df_all[df_all["Surveyor"] == selected_surveyor]
            else:
                filtered_df = df_all
                
            # ফিল্টার করা ডাটা ফ্রেম দেখানো
            st.dataframe(filtered_df, use_container_width=True)
            st.caption(f"Showing {len(filtered_df)} points (Total Recorded: {len(df_all)})")
            
            # অফলাইন ডাউনলোডের জন্য এক্সেল জেনারেটর
            @st.cache_data
            def convert_df_to_excel(dataframe):
                from io import BytesIO
                output = BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    dataframe.to_excel(writer, index=False, sheet_name='GIS_Survey')
                return output.getvalue()

            excel_data = convert_df_to_excel(filtered_df)

            st.download_button(
                label="📥 Export Current View to Excel (.xlsx)",
                data=excel_data,
                file_name=f"GIS_Survey_{selected_surveyor}_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        else:
            st.info("গুগল শিটে এখনো কোনো জিপিএস ডাটা জমা হয়নি।")
    except Exception as e:
        st.error(f"Error loading table: {e}")
