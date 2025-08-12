# nz_energy_dashboard.py
# Run: pip install pandas requests beautifulsoup4 streamlit plotly
# Then: streamlit run nz_energy_dashboard.py

import requests
from bs4 import BeautifulSoup
import io
import pandas as pd
import streamlit as st
import plotly.express as px
from datetime import timedelta

# 1) Find the latest Generation_MD CSV on EMI site
EMI_GEN_PAGE = "https://www.emi.ea.govt.nz/Wholesale/Datasets/Generation/Generation_MD"

def find_latest_generation_csv(page_url=EMI_GEN_PAGE):
    r = requests.get(page_url, timeout=15)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    # look for links ending with '_Generation_MD.csv'
    csv_links = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.lower().endswith("_generation_md.csv"):
            # create absolute URL if needed
            if href.startswith("http"):
                csv_links.append(href)
            else:
                csv_links.append(requests.compat.urljoin(page_url, href))
    # return most recently found (page often lists newest first)
    return csv_links[0] if csv_links else None

# 2) Download CSV into a DataFrame
def download_generation_csv(csv_url):
    r = requests.get(csv_url, timeout=30)
    r.raise_for_status()
    # some EMI CSVs contain odd encodings; pandas can usually parse from bytes
    df = pd.read_csv(io.BytesIO(r.content), low_memory=False)
    return df

# 3) Normalise / aggregate generation by fuel type
def process_generation_df(df):
    # Try to find key columns by common names
    possible_ts_cols = [c for c in df.columns if 'time' in c.lower() or 'date' in c.lower() or 'trading' in c.lower()]
    possible_gen_cols = [c for c in df.columns if 'generation' in c.lower() or 'gen'==c.lower() or 'mw' in c.lower()]
    possible_fuel_cols = [c for c in df.columns if 'fuel' in c.lower() or 'fuel_type' in c.lower() or 'fueltype' in c.lower()]

    # pick guess columns
    ts_col = possible_ts_cols[0] if possible_ts_cols else None
    fuel_col = possible_fuel_cols[0] if possible_fuel_cols else None
    gen_col = None
    for c in ['Generation_MWh','Generation_kWh','Generation','GENERATION','Generation_MW','GEN_MW']:
        if c in df.columns:
            gen_col = c
            break
    if not gen_col:
        # fallback - numeric column that looks like generation
        nums = df.select_dtypes(include='number').columns.tolist()
        gen_col = nums[0] if nums else None

    # Basic cleaning
    if ts_col:
        df[ts_col] = pd.to_datetime(df[ts_col], errors='coerce')
    if gen_col:
        # convert to numeric
        df[gen_col] = pd.to_numeric(df[gen_col], errors='coerce').fillna(0)
    # group by fuel
    if fuel_col and gen_col:
        agg = df.groupby(fuel_col)[gen_col].sum().reset_index()
        agg = agg.sort_values(by=gen_col, ascending=False)
    else:
        # if missing, try grouping by Station / Plant -> map to fuel not available: sum numeric cols
        agg = pd.DataFrame({'category': ['unknown'], 'generation': [df[gen_col].sum() if gen_col else 0]})
        agg.columns = ['FuelType', 'Generation']
    # return cleaned results
    return agg, df, {'ts_col': ts_col, 'fuel_col': fuel_col, 'gen_col': gen_col}

# 4) Compute renewable share helper
RENEWABLE_KEYWORDS = ['hydro','geo','wind','solar','biomass','battery']

def is_renewable(fuel_name):
    if not isinstance(fuel_name, str):
        return False
    fn = fuel_name.lower()
    return any(k in fn for k in RENEWABLE_KEYWORDS)

def compute_renewable_share(agg_df):
    agg_df['is_renewable'] = agg_df.iloc[:,0].apply(is_renewable)
    total = agg_df.iloc[:,1].sum()
    renew = agg_df.loc[agg_df['is_renewable'], agg_df.columns[1]].sum()
    share = (renew / total)*100 if total > 0 else 0
    return round(share,2)

############### Streamlit UI ###############
st.set_page_config(page_title="NZ Energy Live — Electric Kiwi demo", layout="wide")
st.title("🎵 We’re Electric Kiwiiiiiii… Now Let’s See the Data! ⚡")

with st.spinner("Locating latest EMI Generation dataset..."):
    csv_url = find_latest_generation_csv()
    if not csv_url:
        st.error("Could not find a Generation_MD CSV on EMI page. (Try network or EMI page layout changed.)")
        st.stop()
    st.write("Using dataset:", csv_url)

with st.spinner("Downloading & processing data..."):
    try:
        df = download_generation_csv(csv_url)
        agg, raw_df, meta = process_generation_df(df)
    except Exception as e:
        st.error(f"Error downloading or parsing CSV: {e}")
        st.stop()

# Show aggregate fuel mix
if agg is not None and not agg.empty:
    # assume first col is fuel name, second is generation value
    fuel_col_name = agg.columns[0]
    gen_col_name = agg.columns[1]
    st.subheader("Current Fuel Mix (aggregated from CSV)")
    fig_pie = px.pie(agg, names=fuel_col_name, values=gen_col_name, title="Fuel mix")
    st.plotly_chart(fig_pie, use_container_width=True)

    renew_share = compute_renewable_share(agg)
    st.metric(label="Approx. Renewable Share", value=f"{renew_share} %")

    # Green tip
    if renew_share >= 70:
        st.success(f"Green Power Tip: Great day for low-carbon appliances — renewables are {renew_share}%!")
    elif renew_share >= 45:
        st.info(f"Green Power Tip: Moderate renewable share ({renew_share}%) — consider shifting heavy loads to afternoon.")
    else:
        st.warning(f"Green Power Tip: Renewables are low ({renew_share}%) — best to avoid peak usage if you can.")
else:
    st.warning("No aggregate data found in CSV to show fuel mix.")

# Optional: show renewable share over time if the raw data contains timestamp and fuel/time granularity.
if meta.get('ts_col') and meta.get('fuel_col') and meta.get('gen_col'):
    ts = meta['ts_col']
    fuel = meta['fuel_col']
    gen = meta['gen_col']
    # build time-series of renewables %
    # pivot by timestamp and fuel
    pivot = raw_df.pivot_table(index=ts, columns=fuel, values=gen, aggfunc='sum', fill_value=0)
    pivot['total'] = pivot.sum(axis=1)
    # sum renewables per timestamp
    renew_cols = [c for c in pivot.columns if is_renewable(c)]
    if renew_cols:
        pivot['renew_sum'] = pivot[renew_cols].sum(axis=1)
        pivot['renew_share_pct'] = (pivot['renew_sum'] / pivot['total'])*100
        # trim to last 7 days (if timestamps exist)
        last_dt = pivot.index.max()
        last_week = pivot.loc[last_dt - pd.Timedelta(days=7):]
        st.subheader("Renewable share — last 7 days (%)")
        fig_line = px.line(last_week.reset_index(), x=ts, y='renew_share_pct', title="Renewable share (%) over time")
        st.plotly_chart(fig_line, use_container_width=True)
    else:
        st.info("No renewable fuel columns detected for time-series renewable share chart.")
else:
    st.info("CSV lacks clear timestamp/fuel/generation columns for time-series insights (still showing aggregate).")

# Footer: show top of dataframe for inspection
st.subheader("Preview of raw data (first 10 rows)")
st.dataframe(df.head(10))
