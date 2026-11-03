"""A demo UI for the next-day AQI forecast service: pick a city, see tomorrow's air quality.

    uv run streamlit run app.py

It only calls the deployed prediction service (GET /health, POST /predict); the model itself lives in
the aqi_forcasting repository. Set AQI_API_URL to use another deployment, e.g. http://localhost:8080.
"""
import os
from datetime import date, datetime
from zoneinfo import ZoneInfo

import altair as alt
import pandas as pd
import pydeck as pdk
import requests
import streamlit as st

API_URL = os.environ.get('AQI_API_URL', 'https://aqi-forcasting-2.onrender.com').rstrip('/')
TIMEOUT = 180            # the free server sleeps when idle: the first request wakes it, up to a minute

# CPCB's AQI categories, in order, with the colours of its scale (adjusted for contrast). Colour is
# never the only cue: every category is also named, and its AQI range shown.
CATEGORIES = ['Good', 'Satisfactory', 'Moderate', 'Poor', 'Very Poor', 'Severe']
COLORS = ['#18994A', '#8CC63F', '#E0B400', '#F26B1D', '#D32F2F', '#9A2525']
RANGES = ['0–50', '51–100', '101–200', '201–300', '301–400', '401–500']
COLOR = dict(zip(CATEGORIES, COLORS))
RANGE = dict(zip(CATEGORIES, RANGES))
DARK_TEXT = {'Satisfactory', 'Moderate'}          # light fills: dark text reads better on them
HEALTH = {
    'Good': 'Minimal impact.',
    'Satisfactory': 'Minor breathing discomfort for sensitive people.',
    'Moderate': 'Breathing discomfort for people with lung or heart disease, children and older adults.',
    'Poor': 'Breathing discomfort for most people on prolonged exposure.',
    'Very Poor': 'Respiratory illness on prolonged exposure; avoid outdoor activity.',
    'Severe': 'Affects healthy people and seriously affects those with existing diseases; stay indoors.',
}
CITY_COORDS = {
    'Delhi': (28.6139, 77.2090), 'Noida': (28.5355, 77.3910), 'Greater Noida': (28.4744, 77.5040),
    'Ghaziabad': (28.6692, 77.4538), 'Gurugram': (28.4595, 77.0266), 'Faridabad': (28.4089, 77.3178),
    'Lucknow': (26.8467, 80.9462), 'Kanpur': (26.4499, 80.3319), 'Patna': (25.5941, 85.1376),
    'Mumbai': (19.0760, 72.8777), 'Kolkata': (22.5726, 88.3639), 'Chennai': (13.0827, 80.2707),
    'Bengaluru': (12.9716, 77.5946), 'Hyderabad': (17.3850, 78.4867),
}


class ServiceError(Exception):
    pass


# Calls to the prediction service -------------------------------------------------------------------

def call(method, path, **kwargs):
    try:
        r = requests.request(method, f'{API_URL}{path}', timeout=TIMEOUT, **kwargs)
    except requests.RequestException as e:
        raise ServiceError(f'The forecast service did not answer ({type(e).__name__}). Try again in a minute.')
    if r.status_code != 200:
        detail = r.json().get('detail', r.text) if r.headers.get('content-type', '').startswith('application/json') else r.text
        hint = {502: 'CPCB could not be reached from the server just now', 503: 'a data source is unavailable just now'}
        raise ServiceError(f"{hint.get(r.status_code, f'HTTP {r.status_code}')}: {detail}. Try again in a minute.")
    return r.json()


@st.cache_data(ttl=600, show_spinner=False)
def cities():
    return call('GET', '/health')['cities']


@st.cache_data(ttl=900, show_spinner=False)
def live_forecast(city, dangerous_threshold):
    params = {'live': 'true'} | ({'dangerous_threshold': dangerous_threshold} if dangerous_threshold else {})
    return call('POST', '/predict', params=params, json={'city': city})


@st.cache_data(ttl=900, show_spinner=False)
def forecast_from_fields(fields, dangerous_threshold):
    params = {'dangerous_threshold': dangerous_threshold} if dangerous_threshold else {}
    return call('POST', '/predict', params=params, json=dict(fields))


# Pieces of the page --------------------------------------------------------------------------------

def nice_date(day):
    day = date.fromisoformat(day) if isinstance(day, str) else day
    return f'{day:%a} {day.day} {day:%b}'


def category_of(aqi):
    bounds = [50, 100, 200, 300, 400]
    return CATEGORIES[sum(aqi > b for b in bounds)]


def badge(category, size='1rem'):
    text = '#1d1d1b' if category in DARK_TEXT else '#ffffff'
    return (f'<span style="background:{COLOR[category]};color:{text};padding:0.15em 0.6em;border-radius:6px;'
            f'font-weight:600;font-size:{size};white-space:nowrap">{category}</span>')


def probability_chart(probabilities):
    df = pd.DataFrame({'category': CATEGORIES, 'p': [probabilities[c] for c in CATEGORIES],
                       'range': [RANGE[c] for c in CATEGORIES]})
    df['label'] = df['p'].map(lambda p: f'{p:.0%}' if p >= 0.01 else '<1%')
    base = alt.Chart(df).encode(
        y=alt.Y('category:N', sort=CATEGORIES, title=None, axis=alt.Axis(labelLimit=120, ticks=False, domain=False)),
        x=alt.X('p:Q', title='Probability', scale=alt.Scale(domain=[0, 1.08]),
                axis=alt.Axis(format='%', values=[0, 0.25, 0.5, 0.75, 1], gridOpacity=0.4, domain=False)),
        tooltip=[alt.Tooltip('category:N', title='Category'), alt.Tooltip('range:N', title='AQI'),
                 alt.Tooltip('p:Q', title='Probability', format='.1%')],
    )
    bars = base.mark_bar(cornerRadiusEnd=4, height=16).encode(
        color=alt.Color('category:N', scale=alt.Scale(domain=CATEGORIES, range=COLORS), legend=None))
    dark = st.context.theme.type == 'dark'
    labels = base.mark_text(align='left', dx=6, fontSize=13, color='#e6e6e3' if dark else '#31333f'
                            ).encode(text='label:N')
    return (bars + labels).properties(height=6 * 34)


def conditions(inp):
    """What the model saw, in words: the trend and weather it used (not an explanation of the model)."""
    notes = []
    if inp['aqi_diff1'] >= 20:
        notes.append(f"AQI **rose by {inp['aqi_diff1']:.0f}** since the day before.")
    elif inp['aqi_diff1'] <= -20:
        notes.append(f"AQI **fell by {-inp['aqi_diff1']:.0f}** since the day before.")
    else:
        notes.append('AQI was **about the same** as the day before.')
    if abs(inp['aqi_dev7']) >= 40:
        word = 'above' if inp['aqi_dev7'] > 0 else 'below'
        notes.append(f"It is **{abs(inp['aqi_dev7']):.0f} {word}** the previous week's average.")
    wind = inp['wind_speed_mean']
    if wind < 2:
        notes.append(f'**Very little wind** ({wind:.1f} m/s): pollution is not blown away.')
    elif wind > 4:
        notes.append(f'**Windy** ({wind:.1f} m/s): wind helps clear the air.')
    else:
        notes.append(f'Light wind ({wind:.1f} m/s).')
    if inp['precip_sum'] >= 1:
        notes.append(f"**Rain** ({inp['precip_sum']:.0f} mm) washes particles out of the air.")
    else:
        notes.append('**No rain** to wash the air.')
    if inp['month'] in (10, 11, 12, 1):
        notes.append('October to January is the **most polluted season** in north India.')
    pollutants = [name for key, name in [('has_pm25', 'PM2.5'), ('has_pm10', 'PM10'), ('has_no2', 'NO₂'),
                                         ('has_o3', 'O₃'), ('has_co', 'CO'), ('has_so2', 'SO₂')] if inp[key]]
    if pollutants:
        notes.append(f"Main pollutant in the bulletin: **{', '.join(pollutants)}**.")
    if inp['aqi_imputed']:
        notes.append("The bulletin had no reading for this city that day, so the day before's AQI was used.")
    return notes


def check_text(check):
    if 'error' in check:
        return f"Could not check {nice_date(check['date'])}: {check['error']}"
    if check['actual'] is None:
        return f"No CPCB reading for {nice_date(check['date'])}, so the check is not available."
    mark = '✅ correct' if check['correct'] else '❌ missed'
    return (f"For **{nice_date(check['date'])}** the model forecast {badge(check['forecast'], '0.9rem')} "
            f"(from the day before's data). The bulletin reported **AQI {check['actual_aqi']:.0f}**, "
            f"{badge(check['actual'], '0.9rem')}: **{mark}**.")


INPUT_NAMES = {
    'aqi_today': 'AQI on the day', 'aqi_diff1': 'Change since the day before',
    'aqi_roll7_mean': '7-day average AQI', 'aqi_roll7_std': '7-day spread (std)',
    'aqi_dev7': "Difference from the previous week's average", 'temp_mean': 'Temperature, mean (°C)',
    'temp_max': 'Temperature, max (°C)', 'temp_min': 'Temperature, min (°C)', 'temp_range': 'Temperature range (°C)',
    'humidity_mean': 'Humidity (%)', 'dew_point_mean': 'Dew point (°C)', 'precip_sum': 'Rain (mm)',
    'pressure_mean': 'Surface pressure (hPa)', 'cloud_cover_mean': 'Cloud cover (%)',
    'wind_speed_mean': 'Wind speed, mean (m/s)', 'wind_speed_max': 'Wind speed, max (m/s)',
    'wind_u_mean': 'Wind, west→east part (m/s)', 'wind_v_mean': 'Wind, south→north part (m/s)',
    'month': 'Month', 'aqi_imputed': 'AQI filled from the day before (1 = yes)',
}


# The page ------------------------------------------------------------------------------------------

st.set_page_config(page_title='AQI Forecast', page_icon='🌫️', layout='wide')

with st.sidebar:
    st.header('Settings')
    custom_alert = st.toggle('My own alert level', help='By default an alert is raised when the forecast '
                             'itself is Very Poor or Severe.')
    threshold = None
    if custom_alert:
        threshold = st.slider('Alert me when the chance of Very Poor or worse is at least', 5, 90, 25, 5,
                              format='%d%%') / 100
    st.divider()
    st.caption(f'Forecast service: [{API_URL}]({API_URL}/docs)')
    st.caption('Data: CPCB daily AQI bulletins and Open-Meteo weather. The service runs on a free plan: '
               'after a quiet spell the first request can take up to a minute.')

st.title('Air quality forecast')
st.write('Next-day AQI category for 14 Indian cities, forecast by an XGBoost model from the latest '
         'CPCB bulletin, the past week\'s trend and the weather.')

try:
    with st.spinner('Connecting to the forecast service (waking it up if it was asleep)...'):
        city_list = cities()
except ServiceError as e:
    st.error(str(e))
    st.stop()

tab_city, tab_all, tab_whatif, tab_about = st.tabs(['City forecast', 'All cities', 'What if?', 'How it works'])

with tab_city:
    pick, _ = st.columns([1, 2])
    default = city_list.index('Delhi') if 'Delhi' in city_list else 0
    city = pick.selectbox('City', city_list, index=default)
    try:
        with st.spinner(f'Reading the latest CPCB bulletins for {city}...'):
            res = live_forecast(city, threshold)
    except ServiceError as e:
        st.error(str(e))
        st.stop()
    st.session_state['last'] = res
    inp, forecast = res['input'], res['forecast']
    today_in_india = datetime.now(ZoneInfo('Asia/Kolkata')).date()
    when = 'Today' if date.fromisoformat(res['forecast_for']) == today_in_india else 'Tomorrow'

    left, right = st.columns([3, 2], gap='large')
    with left:
        st.markdown(f"#### {when}, {nice_date(res['forecast_for'])} · {city}")
        st.markdown(f"{badge(forecast, '2.2rem')} &nbsp; expected AQI **{RANGE[forecast]}**",
                    unsafe_allow_html=True)
        st.caption(HEALTH[forecast])
        if res['alert']:
            st.warning(f"⚠️ **Alert:** {res['alert_rule']}")
        else:
            st.success(f"No alert: {res['alert_rule']}")

        m1, m2, m3 = st.columns(3)
        m1.metric(f"AQI on {nice_date(res['based_on'])}", f"{inp['aqi_today']:.0f}",
                  f"{inp['aqi_diff1']:+.0f} since the day before", delta_color='inverse')
        m2.metric(f"7-day average · {category_of(inp['aqi_roll7_mean'])}", f"{inp['aqi_roll7_mean']:.0f}")
        m3.metric('Chance of Very Poor or worse', f"{res['p_dangerous']:.0%}")

    with right:
        st.markdown('#### How likely is each category?')
        st.altair_chart(probability_chart(res['probabilities']), width='stretch')

    st.divider()
    c1, c2 = st.columns(2, gap='large')
    with c1:
        st.markdown('#### How did the model do today?')
        if 'check' in res:
            st.markdown(check_text(res['check']), unsafe_allow_html=True)
            st.caption('Checked against the CPCB bulletin, the source the model learned from.')
        else:
            st.caption('This version of the forecast service does not report a check yet.')
    with c2:
        st.markdown('#### What the model saw')
        st.markdown('\n'.join(f'- {n}' for n in conditions(inp)))

    with st.expander('All 27 inputs, and the probabilities as a table'):
        rows = [(INPUT_NAMES.get(k, k), v) for k, v in inp.items() if k in INPUT_NAMES]
        flags = ', '.join(k.removeprefix('has_').upper() for k in inp if k.startswith('has_') and inp[k]) or 'none'
        rows.append(('Main pollutants in the bulletin', flags))
        a, b = st.columns(2)
        a.dataframe(pd.DataFrame(rows, columns=['Input', 'Value']).astype({'Value': str}),
                    hide_index=True, width='stretch')
        b.dataframe(pd.DataFrame({'Category': CATEGORIES, 'AQI': RANGES,
                                  'Probability': [f"{res['probabilities'][c]:.1%}" for c in CATEGORIES]}),
                    hide_index=True, width='stretch')

with tab_all:
    st.write('Tomorrow\'s forecast for every city, from each one\'s latest CPCB bulletin.')
    if st.button('Forecast all 14 cities', type='primary'):
        results, failed = [], []
        progress = st.progress(0.0)
        for i, c in enumerate(city_list):
            progress.progress(i / len(city_list), text=f'{c}...')
            try:
                results.append(live_forecast(c, threshold))
            except ServiceError:
                failed.append(c)
        progress.empty()
        st.session_state['all'] = (results, failed)

    if 'all' in st.session_state:
        results, failed = st.session_state['all']
        if failed:
            st.warning(f"No forecast for {', '.join(failed)} just now: try again in a minute.")
        rows = pd.DataFrame([{
            'City': r['city'], 'AQI now': r['input']['aqi_today'], 'Forecast': r['forecast'],
            'Chance of Very Poor+': round(r['p_dangerous'] * 100), 'Alert': '⚠️' if r['alert'] else '',
            'Model today': {True: '✅', False: '❌'}.get(r.get('check', {}).get('correct'), ''),
        } for r in results]).sort_values('Chance of Very Poor+', ascending=False)

        checked = [r['check']['correct'] for r in results if r.get('check', {}).get('correct') is not None]
        if checked:
            st.markdown(f"Today the model was right in **{sum(checked)} of {len(checked)}** cities.")

        mapcol, tablecol = st.columns([2, 3], gap='large')
        with tablecol:
            st.dataframe(rows, hide_index=True, width='stretch', height=35 * (len(rows) + 1) + 3, column_config={
                'AQI now': st.column_config.NumberColumn(format='%d'),
                'Chance of Very Poor+': st.column_config.ProgressColumn(format='%d%%', min_value=0, max_value=100),
                'Model today': st.column_config.TextColumn(help='Was the forecast for the latest day right?'),
            })
        with mapcol:
            points = pd.DataFrame([{
                'city': r['city'], 'forecast': r['forecast'], 'lat': CITY_COORDS[r['city']][0],
                'lon': CITY_COORDS[r['city']][1], 'aqi': int(r['input']['aqi_today']),
                'rgb': [int(COLOR[r['forecast']][i:i + 2], 16) for i in (1, 3, 5)],
            } for r in results if r['city'] in CITY_COORDS])
            st.pydeck_chart(pdk.Deck(
                layers=[pdk.Layer('ScatterplotLayer', points, get_position='[lon, lat]', get_fill_color='rgb',
                                  get_radius=45000, radius_min_pixels=7, pickable=True, stroked=True,
                                  get_line_color=[255, 255, 255], line_width_min_pixels=2)],
                initial_view_state=pdk.ViewState(latitude=22.5, longitude=80, zoom=3.6),
                tooltip={'text': '{city}\nTomorrow: {forecast}\nAQI now: {aqi}'},
            ), width='stretch')
            st.markdown(' '.join(badge(c, '0.8rem') for c in CATEGORIES), unsafe_allow_html=True)

with tab_whatif:
    if 'last' not in st.session_state:
        st.info('Get a city forecast first, on the first tab.')
    else:
        base = st.session_state['last']
        inp = base['input']
        st.write(f"Start from **{base['city']}** on {nice_date(base['based_on'])} and change the weather "
                 'that day: how would the forecast change? Everything else stays as measured.')
        s1, s2 = st.columns(2)
        wind = s1.slider('Mean wind speed (m/s)', 0.0, 8.0, float(round(inp['wind_speed_mean'], 1)), 0.1)
        rain = s2.slider('Rain (mm)', 0.0, 40.0, float(round(inp['precip_sum'], 1)), 0.5)

        fields = dict(inp)
        scale = wind / inp['wind_speed_mean'] if inp['wind_speed_mean'] > 0 else 1.0
        fields.update(wind_speed_mean=wind, wind_speed_max=round(inp['wind_speed_max'] * scale, 2),
                      wind_u_mean=round(inp['wind_u_mean'] * scale, 2),
                      wind_v_mean=round(inp['wind_v_mean'] * scale, 2), precip_sum=rain)
        try:
            new = forecast_from_fields(tuple(sorted(fields.items())), threshold)
        except ServiceError as e:
            st.error(str(e))
        else:
            a, b = st.columns([2, 3], gap='large')
            with a:
                st.markdown(f"As measured: {badge(base['forecast'])} &nbsp;→&nbsp; What if: {badge(new['forecast'])}",
                            unsafe_allow_html=True)
                st.metric('Chance of Very Poor or worse', f"{new['p_dangerous']:.0%}",
                          f"{(new['p_dangerous'] - base['p_dangerous']) * 100:+.0f} points", delta_color='inverse')
            with b:
                st.altair_chart(probability_chart(new['probabilities']), width='stretch')
            st.caption('The model learned these effects from 2015–2024 data; they are associations, '
                       'not a weather simulation.')

with tab_about:
    st.markdown('''
**What it forecasts.** Tomorrow's AQI category from CPCB's daily bulletin (published about 4 PM IST)
for 14 cities. Before 4 PM, today's bulletin is not out yet, so the forecast is for today.

**How.** An XGBoost model trained on 2015–2024 learned how today's AQI, its 7-day trend, the weather,
the month and the city relate to the next day's category. For each forecast the service downloads the
last 11 CPCB bulletins and that day's weather (Open-Meteo), and builds the same 27 inputs as in training.

**How good it is** (tested on 2025, a year it never saw):
- right category on **75%** of days
- catches **83%** of Very Poor or Severe days; **78%** of its Very Poor-or-worse warnings are right
- hardest case: days when the category **changes**, right on 28% of them (on days with no change, 92%)

**This app** only calls the forecast service; the model and its code live in the project repository.
''')
    st.caption(f'Service documentation: {API_URL}/docs')
