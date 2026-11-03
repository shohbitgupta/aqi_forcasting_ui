# AQI Forecast: demo UI

A Streamlit app for the next-day AQI forecast of 14 Indian cities. Pick a city and see tomorrow's
CPCB air-quality category, how likely each category is, how the model did on the latest day, and the
conditions it saw.

The app only **calls the deployed forecast service**; the model, its training and the service live in
the [aqi_forcasting](https://github.com/shohbitgupta/aqi_forcasting) repository.

| Tab | What it shows |
|---|---|
| **City forecast** | the forecast for one city, the probability of every category, an alert, today's check against the CPCB bulletin, and the trend and weather the model used |
| **All cities** | all 14 cities on a map and in a table, sorted by the chance of Very Poor or worse, and in how many cities the model was right today |
| **What if?** | change the wind and rain of the latest day and see how the forecast moves |
| **How it works** | the data, the model and how well it did on 2025 |

In the sidebar, **My own alert level** raises an alert when the chance of Very Poor or worse reaches
your threshold, instead of only when the forecast itself is Very Poor or Severe.

## Run it

```bash
uv sync
uv run streamlit run app.py              # opens http://localhost:8501
```

It uses the deployed service, https://aqi-forcasting-2.onrender.com. To use another one, for example
the service running locally from the aqi_forcasting repository:

```bash
AQI_API_URL=http://localhost:8080 uv run streamlit run app.py
```

The service runs on Render's free plan, which sleeps after 15 minutes without requests: the first
forecast after that can take up to a minute. Open the app a few minutes before a demo.

## Deploy it (Streamlit Community Cloud, free)

1. Push this folder to its own GitHub repository.
2. On https://share.streamlit.io choose **Create app**, pick the repository, branch `main` and
   `app.py`. It installs `requirements.txt`.
3. Optional: to use another forecast service, add `AQI_API_URL = "https://..."` under the app's
   **Settings → Secrets**; top-level secrets are passed to the app as environment variables.

`requirements.txt` is made from `uv.lock`; after changing dependencies, run
`uv export --no-hashes --no-dev -o requirements.txt`.

## Files

```
app.py                  the whole app
.streamlit/config.toml  accent colour for light and dark mode; the app follows the viewer's setting
pyproject.toml, uv.lock dependencies (uv)
requirements.txt        the same, for Streamlit Community Cloud
```

The category colours follow CPCB's AQI scale, adjusted for contrast. Colour is never the only cue:
every category is also written out, with its AQI range.

<img width="1470" height="719" alt="Screenshot 2026-11-03 at 16 16 15" src="https://github.com/user-attachments/assets/b1d854c9-06a1-425d-8409-efcc5c06f1a0" />
