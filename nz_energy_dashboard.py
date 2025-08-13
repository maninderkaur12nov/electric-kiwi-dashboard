import pandas as pd
import requests
from io import StringIO
import streamlit as st
import plotly.express as px
from datetime import datetime, timedelta

# Configuration
EMI_API_BASE = "https://www.emi.ea.govt.nz/Wholesale/Datasets/Generation/"
DATASET_NAME = "Generation_MD"
RENEWABLE_SOURCES = ['HYDRO', 'WIND', 'GEOTHERMAL', 'SOLAR']
NON_RENEWABLE_SOURCES = ['GAS', 'COAL', 'DIESEL', 'CO-GEN']

@st.cache_data
def fetch_recent_generation_data(days_to_fetch=30):
    """Fetch recent generation data from EMI"""
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days_to_fetch)
    date_range = pd.date_range(start_date, end_date, freq='D')
    
    all_data = []
    
    for date in date_range:
        date_str = date.strftime("%Y%m%d")
        url = f"{EMI_API_BASE}{DATASET_NAME}/{DATASET_NAME}_{date_str}.csv"
        
        try:
            response = requests.get(url)
            response.raise_for_status()
            df = pd.read_csv(StringIO(response.text))
            df['DateTime'] = pd.to_datetime(df['TradingPeriod']) + pd.to_timedelta(df['TradingPeriod']-1, unit='h')
            all_data.append(df)
        except Exception as e:
            st.warning(f"Could not fetch data for {date_str}: {e}")
    
    if not all_data:
        st.error("No data could be fetched. Please check your internet connection.")
        return pd.DataFrame()
    
    return pd.concat(all_data)

def clean_and_process_data(df):
    """Clean and process the generation data"""
    if df.empty:
        return df
    
    # Standardize column names and values
    df.columns = df.columns.str.strip()
    df['FuelType'] = df['FuelType'].str.strip().str.upper()
    df['Generation'] = pd.to_numeric(df['Generation'], errors='coerce')
    
    # Categorize fuel types
    df['Category'] = df['FuelType'].apply(
        lambda x: 'Renewable' if x in RENEWABLE_SOURCES 
        else 'Non-Renewable' if x in NON_RENEWABLE_SOURCES 
        else 'Other'
    )
    
    # Extract date components for easier analysis
    df['Date'] = df['DateTime'].dt.date
    df['Hour'] = df['DateTime'].dt.hour
    
    return df.dropna(subset=['Generation'])

def create_dashboard(df):
    """Create the Streamlit dashboard with interactive visualizations"""
    st.title("New Zealand Electricity Generation Analysis (Market Data)")
    
    if df.empty:
        st.warning("No data available to display.")
        return
    
    # Date range selector
    min_date = df['Date'].min()
    max_date = df['Date'].max()
    selected_dates = st.date_input(
        "Select date range",
        value=(min_date, max_date),
        min_value=min_date,
        max_value=max_date
    )
    
    if len(selected_dates) == 2:
        start_date, end_date = selected_dates
        filtered_df = df[(df['Date'] >= start_date) & (df['Date'] <= end_date)]
    else:
        filtered_df = df
    
    # Overall summary
    st.header("Energy Mix Analysis")
    
    # Calculate totals
    total_generation = filtered_df['Generation'].sum()
    renewable_pct = filtered_df[filtered_df['Category'] == 'Renewable']['Generation'].sum() / total_generation * 100
    
    col1, col2 = st.columns(2)
    col1.metric("Total Generation", f"{total_generation:,.0f} MWh")
    col2.metric("Renewable Percentage", f"{renewable_pct:.1f}%")
    
    # Pie chart by category
    cat_sum = filtered_df.groupby('Category')['Generation'].sum().reset_index()
    fig1 = px.pie(cat_sum, values='Generation', names='Category', 
                 title="Generation by Category")
    st.plotly_chart(fig1, use_container_width=True)
    
    # Bar chart by fuel type
    fuel_sum = filtered_df.groupby('FuelType')['Generation'].sum().reset_index()
    fig2 = px.bar(fuel_sum.sort_values('Generation', ascending=False), 
                 x='FuelType', y='Generation', 
                 title="Generation by Fuel Type",
                 color='FuelType')
    st.plotly_chart(fig2, use_container_width=True)
    
    # Time series analysis
    st.header("Time Series Analysis")
    
    # Daily generation trend
    daily_data = filtered_df.groupby(['Date', 'Category'])['Generation'].sum().reset_index()
    fig3 = px.line(daily_data, x='Date', y='Generation', color='Category',
                  title="Daily Generation Trend")
    st.plotly_chart(fig3, use_container_width=True)
    
    # Hourly pattern
    hourly_data = filtered_df.groupby(['Hour', 'Category'])['Generation'].mean().reset_index()
    fig4 = px.line(hourly_data, x='Hour', y='Generation', color='Category',
                  title="Average Hourly Generation Pattern")
    st.plotly_chart(fig4, use_container_width=True)

def main():
    st.set_page_config(page_title="NZ Electricity Dashboard", layout="wide")
    
    with st.spinner("Fetching latest generation data..."):
        raw_data = fetch_recent_generation_data(days_to_fetch=30)
        processed_data = clean_and_process_data(raw_data)
    
    if not processed_data.empty:
        create_dashboard(processed_data)
        
        # Raw data explorer
        st.header("Data Explorer")
        with st.expander("View raw data"):
            st.dataframe(processed_data.sort_values('DateTime'))
            
        # Download option
        csv = processed_data.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="Download processed data as CSV",
            data=csv,
            file_name="nz_generation_data.csv",
            mime="text/csv"
        )

if __name__ == "__main__":
    main()