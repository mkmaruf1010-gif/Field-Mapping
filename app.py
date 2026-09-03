import streamlit as st
import pandas as pd
import ee
import json
from datetime import datetime
from streamlit_js_eval import get_geolocation

st.set_page_config(page_title="Multi-User GIS Field Collector", layout="wide")

# --- ১. গুগল আর্থ ইঞ্জিন অথেন্টিকেশন ---
@st.cache_resource
def init_earth_engine():
    try:
        # TOML এর [gee_credentials] সরাসরি পড়া
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

# বৈশ্বিক চলক ইনিশিয়ালাইজেশন
gee_active = init_earth_engine()

import requests

def get_elevation(lat, lon):
    # ১ম চেষ্টা: Google Earth Engine (SRTM 30m)
    if gee_active:
        try:
            point = ee.Geometry.Point([lon, lat]) # Longitude, Latitude ক্রম সঠিক রাখা জরুরি
            dem = ee.Image('USGS/SRTM30M')
            elevation_data = dem.reduceRegion(
                reducer=ee.Reducer.first(),
                geometry=point,
                scale=30
            ).getInfo()
            
            val = elevation_data.get('elevation')
            if val is not None:
                return round(val, 2)
        except Exception:
            pass

    # ২য় চেষ্টা (Fallback): Open-Elevation Free REST API
    try:
        url = f"https://api.open-elevation.com/api/v1/lookup?locations={lat},{lon}"
        response = requests.get(url, timeout=5).json()
        return response['results'][0]['elevation']
    except Exception:
        return "N/A"

# --- ৩. সেশন স্টেট ইনিশিয়ালাইজেশন (ডাটা টেবিলে জমা রাখার জন্য) ---
if 'field_data' not in st.session_state:
    st.session_state.field_data = []

# --- ৪. ইউজার ইন্টারফেস (UI) ---
st.title("📍 Smart GIS Field GPS & Elevation Collector")
st.caption("Multi-User Live Geolocation & Google Earth Elevation Processing")

# সার্ভেয়ার তথ্য
col1, col2 = st.columns(2)
with col1:
    surveyor_name = st.text_input("Surveyor Name / ID", "Surveyor_1")
with col2:
    feature_type = st.selectbox("Feature Type", ["Point of Interest", "Water Body", "Road Node", "Boundary Point"])

st.markdown("---")

# ৫. লাইভ জিপিএস ক্যাপচার (Streamlit JS Eval)
st.subheader("১. লাইভ কোঅর্ডিনেট ক্যাপচার")
loc = get_geolocation()

if loc and 'coords' in loc:
    lat = loc['coords']['latitude']
    lon = loc['coords']['longitude']
    accuracy = loc['coords']['accuracy']

    st.markdown(
    f"<div style='padding: 10px; background-color: #d4edda; color: #155724; border-radius: 5px;'>"
    f"<b>GPS Location Fetched!</b><br>Latitude: {lat:.6f} | Longitude: {lon:.6f} (Accuracy: ±{accuracy:.1f}m)"
    f"</div>", 
    unsafe_allow_html=True
)

    # ৬. পয়েন্ট সেভ করার বাটন
    if st.button("➕ Capture & Add to Field Sheet"):
        # গুগল আর্থ ইঞ্জিন থেকে এলিভেশন আনা
        elevation = get_elevation(lat, lon)
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        point_entry = {
            "Point_ID": len(st.session_state.field_data) + 1,
            "Surveyor": surveyor_name,
            "Feature_Type": feature_type,
            "Latitude": lat,
            "Longitude": lon,
            "Elevation_m (GEE)": elevation if elevation is not None else "N/A",
            "GPS_Accuracy_m": accuracy,
            "Timestamp": timestamp
        }
        
        st.session_state.field_data.append(point_entry)
        st.toast(f"Point #{point_entry['Point_ID']} Added Successfully!")

else:
    st.warning("⚠️ অনুগ্রহ করে ব্রাউজারের Location Permission 'Allow' করুন এবং জিপিএস অন রাখুন।")

# --- ৭. এক্সেল ফিল্ড শিট ও ডেটাবেস ভিউ ---
st.markdown("---")
st.subheader("২. সংগৃহীত ফিল্ড শিট (Live Sheet)")

if st.session_state.field_data:
    df = pd.DataFrame(st.session_state.field_data)
    st.dataframe(df, use_container_width=True)

    # এক্সেল ডাউলোড প্রসেসিং
    @st.cache_data
    def convert_df_to_excel(dataframe):
        from io import BytesIO
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            dataframe.to_excel(writer, index=False, sheet_name='GIS_Survey')
        return output.getvalue()

    excel_data = convert_df_to_excel(df)

    st.download_button(
        label="📥 Export Field Sheet to Excel (.xlsx)",
        data=excel_data,
        file_name=f"GIS_Field_Survey_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
else:
    st.info("এখনো কোনো জিপিএস পয়েন্ট ক্যাপচার করা হয়নি।")
