import requests
from bs4 import BeautifulSoup
import io
import pandas as pd
import streamlit as st
import plotly.express as px

# EMI generation data URL page
EMI_GEN_PAGE = "https://www.emi.ea.govt.nz/Wholesale/Datasets/Generation/Generation_MD"

def find_latest_generation_csv(page_url=EMI_GEN_PAGE):
    r = requests.get(page_url, timeout=15)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    csv_links = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.lower().endswith("_generation_md.csv"):
            if href.startswith("http"):
                csv_links.append(href)
            else:
                csv_links.append(requests.compat.urljoin(page_url, href))
    return csv_links[0] if csv_links else None

def download_generation_csv(csv_url):
    r = requests.get(csv_url, timeout=30)
    r.raise_for_status()
    df = pd.read_csv(io.BytesIO(r.content), low_memory=False)
    return df

def clean_and_aggregate(df):
    df.columns = [c.strip() for c in df.columns]

    date_col = None
    period_col = None
    fuel_col = None
    gen_col = None

    for col in df.columns:
        low = col.lower()
        if 'date' in low:
            date_col = col
        elif 'period' in low:
            period_col = col
        elif 'fuel' in low:
            fuel_col = col
        elif 'generation' in low or 'mw' in low:
            gen_col = col

    if not all([date_col, period_col, fuel_col, gen_col]):
        st.error("Could not find required columns in the CSV.")
        st.stop()

    df[date_col] = pd.to_datetime(df[date_col], errors='coerce')
    df['Hour'] = ((df[period_col] - 1) // 2).astype(int)
    df['Timestamp'] = df[date_col] + pd.to_timedelta(df['Hour'], unit='h')

    df[fuel_col] = df[fuel_col].str.lower().str.strip()

    renewables_list = ['hydro', 'wind', 'solar', 'geothermal', 'biomass']
    df['Fuel_Category'] = df[fuel_col].apply(lambda x: 'Renewable' if any(r in x for r in renewables_list) else 'Non-Renewable')

    df[gen_col] = pd.to_numeric(df[gen_col], errors='coerce').fillna(0)

    agg = df.groupby(['Timestamp', 'Fuel_Category'])[gen_col].sum().unstack(fill_value=0)

    agg['Total_Generation'] = agg.sum(axis=1)
    agg['Renewable_Share'] = (agg.get('Renewable', 0) / agg['Total_Generation']) * 100
    agg['Renewable_Share_Smooth'] = agg['Renewable_Share'].rolling(window=3, min_periods=1).mean()

    return agg, df

# Pagination helpers
def paginate_df(df, page_size=10, key="page_selector"):
    total_rows = len(df)
    total_pages = (total_rows // page_size) + (1 if total_rows % page_size else 0)
    page_num = st.number_input(
        "Select page",
        min_value=1,
        max_value=total_pages,
        value=1,
        step=1,
        key=key
    )
    start_idx = (page_num - 1) * page_size
    end_idx = start_idx + page_size
    st.write(f"Showing rows {start_idx + 1} to {min(end_idx, total_rows)} of {total_rows}")
    st.dataframe(df.iloc[start_idx:end_idx])

def paginate_timeseries(df, page_size=24, key="timeseries_page_selector"):
    total_points = len(df)
    total_pages = (total_points // page_size) + (1 if total_points % page_size else 0)
    page_num = st.number_input(
        "Select time range page",
        min_value=1,
        max_value=total_pages,
        value=1,
        step=1,
        key=key
    )
    start_idx = (page_num - 1) * page_size
    end_idx = start_idx + page_size
    return df.iloc[start_idx:end_idx], page_num

# Streamlit app start
st.set_page_config(page_title="NZ Energy Live — Electric Kiwi demo", layout="wide")
st.title("🎵 We’re Electric Kiwiiiiiii… Now Let’s See the Data! ⚡")

with st.spinner("Locating latest EMI Generation dataset..."):
    csv_url = find_latest_generation_csv()
    if not csv_url:
        st.error("Could not find a Generation_MD CSV on EMI page.")
        st.stop()
    st.write("Using dataset:", csv_url)

with st.spinner("Downloading & processing data..."):
    try:
        agg, raw_df = clean_and_aggregate(download_generation_csv(csv_url))
    except Exception as e:
        st.error(f"Error downloading or processing CSV: {e}")
        st.stop()

# Latest fuel mix pie chart
latest = agg.iloc[-1]
pie_data = latest[['Renewable', 'Non-Renewable']].fillna(0)

st.subheader("Current Fuel Mix")
fig_pie = px.pie(
    names=pie_data.index,
    values=pie_data.values,
    color=pie_data.index,
    color_discrete_map={'Renewable':'green', 'Non-Renewable':'red'},
    title="Renewable vs Non-Renewable Generation"
)
st.plotly_chart(fig_pie, use_container_width=True)

# Renewable share line chart with pagination
st.subheader("Renewable Share Trend (Last 7 Days)")
last_7days = agg.loc[agg.index >= (agg.index.max() - pd.Timedelta(days=7))]
paginated_ts, current_page = paginate_timeseries(last_7days, page_size=24)
fig_line = px.line(
    paginated_ts,
    y='Renewable_Share_Smooth',
    labels={'Renewable_Share_Smooth': 'Renewable Share (%)', 'Timestamp': 'Date & Time'},
    title=f"Renewable Share (%) Over Time (Page {current_page})"
)
st.plotly_chart(fig_line, use_container_width=True)

# Green power tips banner
renew_share_latest = latest['Renewable_Share']
if renew_share_latest >= 70:
    st.success(f"Green Power Tip: Great day for low-carbon appliances — renewables are {renew_share_latest:.1f}%!")
elif renew_share_latest >= 45:
    st.info(f"Green Power Tip: Moderate renewable share ({renew_share_latest:.1f}%) — consider shifting heavy loads to afternoon.")
else:
    st.warning(f"Green Power Tip: Renewables are low ({renew_share_latest:.1f}%) — best to avoid peak usage if you can.")

# Raw data preview with pagination
st.subheader("Raw Data Preview (Paginated)")
paginate_df(raw_df, page_size=10)
