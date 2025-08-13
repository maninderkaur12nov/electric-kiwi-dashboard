import pandas as pd
import requests
from io import BytesIO
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import streamlit as st
import plotly.express as px

# Configuration
EMI_BASE_URL = "https://www.emi.ea.govt.nz"
EMI_GEN_PAGE = f"{EMI_BASE_URL}/Wholesale/Datasets/Generation/Generation_MD"
RENEWABLE_SOURCES = ['HYDRO', 'WIND', 'GEOTHERMAL', 'SOLAR']
NON_RENEWABLE_SOURCES = ['GAS', 'COAL', 'DIESEL', 'CO-GEN']

def get_monthly_files():
    """Fetch list of available monthly generation files"""
    try:
        response = requests.get(EMI_GEN_PAGE, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        files = []
        for row in soup.select('tr'):
            cols = row.select('td')
            if len(cols) >= 3:  # Check if it's a file row
                name = cols[0].get_text(strip=True)
                if name.endswith('_Generation_MD.csv'):
                    file_url = urljoin(EMI_GEN_PAGE + "/", name)
                    month_year = name.split('_')[0]  # Get YYYYMM
                    files.append((month_year, file_url))
        return files
    
    except Exception as e:
        st.error(f"Error fetching file list: {str(e)}")
        return []

def process_generation_data(df, month_year):
    """Process generation data with proper date handling"""
    # Standardize column names
    df.columns = df.columns.str.strip().str.upper()
    
    # Convert Trading_Date to datetime - handles both formats
    try:
        # Try ISO format first (YYYY-MM-DD)
        df['DATE'] = pd.to_datetime(df['TRADING_DATE'], format='ISO8601')
    except ValueError:
        try:
            # Try day-first format (DD-MM-YYYY)
            df['DATE'] = pd.to_datetime(df['TRADING_DATE'], dayfirst=True)
        except ValueError:
            # Fallback to infer format
            df['DATE'] = pd.to_datetime(df['TRADING_DATE'], infer_datetime_format=True)
    
    # Process generation values (TP1-TP48)
    tp_cols = [col for col in df.columns if col.startswith('TP') and col[2:].isdigit()]
    df['DAILY_GENERATION'] = df[tp_cols].sum(axis=1)
    
    # Categorize generation
    df['CATEGORY'] = df['FUEL_CODE'].str.strip().str.upper().apply(
        lambda x: 'Renewable' if x in RENEWABLE_SOURCES 
        else 'Non-Renewable' if x in NON_RENEWABLE_SOURCES 
        else 'Other'
    )
    
    return df

def main():
    st.set_page_config(page_title="NZ Plant Generation", layout="wide")
    st.title("NZ Electricity Generation by Plant")
    
    # Fetch available files
    with st.spinner("Loading available data files..."):
        monthly_files = get_monthly_files()
    
    if not monthly_files:
        st.error("No generation files found")
        return
    
    # File selection
    selected_file = st.selectbox(
        "Select month to analyze",
        options=[f"{month[:4]}/{month[4:]} ({url.split('/')[-1]})" 
                for month, url in monthly_files],
        index=0
    )
    
    # Get selected URL
    selected_url = next(
        url for month, url in monthly_files 
        if f"{month[:4]}/{month[4:]} ({url.split('/')[-1]})" == selected_file
    )
    
    # Download and process data
    with st.spinner(f"Processing {selected_file}..."):
        try:
            response = requests.get(selected_url, timeout=30)
            response.raise_for_status()
            df = pd.read_csv(BytesIO(response.content), low_memory=False)
            month_year = selected_url.split('/')[-1].split('_')[0]
            processed_df = process_generation_data(df, month_year)
            
            # Display analysis
            st.header(f"Plant Generation - {month_year[:4]}/{month_year[4:]}")
            
            # Plant selection
            plants = processed_df['GEN_CODE'].unique()
            selected_plant = st.selectbox("Select Plant", sorted(plants))
            
            # Filter data for selected plant
            plant_df = processed_df[processed_df['GEN_CODE'] == selected_plant]
            
            # Plant metadata
            st.subheader(f"Plant Information: {selected_plant}")
            cols = st.columns(4)
            cols[0].metric("Site Code", plant_df['SITE_CODE'].iloc[0])
            cols[1].metric("Network Code", plant_df['NWK_CODE'].iloc[0])
            cols[2].metric("Fuel Type", plant_df['FUEL_CODE'].iloc[0])
            cols[3].metric("Technology", plant_df['TECH_CODE'].iloc[0])
            
            # Generation metrics
            total_gen = plant_df['DAILY_GENERATION'].sum()
            avg_daily = plant_df['DAILY_GENERATION'].mean()
            
            cols = st.columns(2)
            cols[0].metric("Total Generation", f"{total_gen:,.0f} MWh")
            cols[1].metric("Average Daily", f"{avg_daily:,.0f} MWh")
            
            # Daily generation trend
            st.subheader("Daily Generation Pattern")
            fig1 = px.line(plant_df, x='DATE', y='DAILY_GENERATION',
                          title=f"Daily Generation for {selected_plant}")
            st.plotly_chart(fig1, use_container_width=True)
            
            # Raw data
            with st.expander("View Plant Data"):
                st.dataframe(plant_df.sort_values('DATE'))
                
        except Exception as e:
            st.error(f"Error processing data: {str(e)}")

if __name__ == "__main__":
    main()