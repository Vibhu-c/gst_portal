# Smart GST & Compliance Management System

This is a college-project-ready GST portal built with Streamlit.

## Features
- Company registration with GSTIN and state code.
- Public company data fetch using Yahoo Finance API (`yfinance`):
  - Turnover proxy: `Total Revenue`
  - Purchase proxy: `Cost Of Revenue`
- Monthly GST entry per company and financial year.
- Return reporting columns for:
  - `GSTR-1`
  - `GSTR-3B`
  - `GSTR-2A`
  - `ITC Claimed`
  - `TDS Received`
  - `TCS Received`
- Tax simulation:
  - CGST + SGST for intra-state
  - IGST for inter-state
  - Net tax payable after ITC/TDS/TCS credits
- Smart compliance insights and basic anomaly flags.
- Smart compliance score, notice center, due-date monitor, penalty estimator, invoice risk review and liability forecast.
- Invoice-driven GSTR-1, auto-populated GSTR-3B, filing acknowledgement PDF and digital-signature style confirmation.
- Downloadable CSV annual report.

## Project Structure
- `app.py` - Streamlit UI and workflow
- `db.py` - SQLite schema and data access
- `gst_engine.py` - GST calculation and smart insights
- `company_api.py` - Public company financial data fetch
- `gst_portal.db` - generated automatically on first run

## Run Locally
```bash
cd /Users/vaibhavsrivastava/Documents/Playground/smart-gst-portal
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## One-Command Web Start
```bash
cd /Users/vaibhavsrivastava/Documents/Playground/smart-gst-portal
./run_web.sh
```
Then open `http://localhost:8501`.

## Run with Docker (Web)
```bash
cd /Users/vaibhavsrivastava/Documents/Playground/smart-gst-portal
docker build -t smart-gst-portal .
docker run -p 8501:8501 smart-gst-portal
```

## Deploy Publicly (Render - Free)
1. Push this folder to a GitHub repository.
2. Go to [Render](https://render.com) and sign in.
3. Click **New +** -> **Blueprint**.
4. Connect your GitHub repo and select it.
5. Render will detect `render.yaml` and create the web service.
6. After deployment, you will get a URL like:
   - `https://smart-gst-portal.onrender.com`

### Exact GitHub Push Commands
Run these inside this project folder after creating an empty GitHub repository:
```bash
git init
git add .
git commit -m "Deploy Smart GST portal"
git branch -M main
git remote add origin YOUR_GITHUB_REPO_URL
git push -u origin main
```

## Deploy Publicly (Streamlit Community Cloud)
1. Push this folder to GitHub.
2. Go to [Streamlit Community Cloud](https://share.streamlit.io/).
3. Click **Create app** and select:
   - Repository: your repo
   - Branch: `main`
   - Main file path: `app.py`
4. Deploy and use the generated URL.

## Get It On Google Search
After you get a public URL:
1. Open [Google Search Console](https://search.google.com/search-console/about).
2. Add your website URL as a property.
3. Verify ownership (recommended: DNS record).
4. Use **URL Inspection** -> paste your homepage URL -> **Request Indexing**.
5. Wait for indexing (can take days to weeks).

## Demo Flow for Presentation
1. Register your company in **Company Setup**.
2. Use **Public Company API** tab to fetch turnover/purchase data for any listed company ticker (for example `RELIANCE.NS`, `TCS.NS`, `INFY.NS`).
3. Add monthly data in **Monthly GST Entry** for different months.
4. Open **Returns & Reports** to show GSTR-1, GSTR-3B, GSTR-2A and ITC/TDS/TCS columns.
5. Show **Smart Insights** tab to explain AI/automation compliance layer.

## Notes
- This is a project portal for academic demonstration, not an official government filing portal.
- Public API data can vary by ticker and availability.
