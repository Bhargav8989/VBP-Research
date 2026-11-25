# VBP Research — Indian Stock & IPO Analyzer

**VBP Research** is a free, open-access web application for Indian equity and IPO research on **NSE/BSE** stocks. It combines an **event-study analyzer** (Quarterly Results, AGM, and Custom dates) with a **GMP-free SME & Regular (Mainboard) IPO Fundamental & Valuation Report** — with no login or subscription required.

---

## Features

### 1. Results & AGM Event-Study Analyzer (NSE Stocks)
- **Event Modes:** Analyze historical **Quarterly Results**, **AGMs**, or **Custom** (`YYYY-MM-DD`) dates across the last 4, 8, 12, or 20 events.
- **Configurable Window:** Set **Before (`T-`)** and **After (`T+`)** trading days (`1–120`).
- **Upcoming Event Alerts:** Automatically surfaces upcoming scheduled Results/AGM dates.
- **Regular & F&O Setups + KPIs:** Directional tendency cards and key return/win-rate metrics.
- **Auto Range Guide:** Compares multiple `T- / T+` windows (`Pre %`, `Post %`, `Total %`, `Win %`) and lets you apply any window in one click.
- **Interactive Charts (ECharts):**
  - **Event Trace Overlay:** All past events aligned at `T0` with Average Pattern, `₹ Price`, `All Events`, and `Median` toggles.
  - **Single-Event Drill-Down:** Click any event row to inspect its exact closing `₹` price and daily volume around `T0`.
- **Event Breakdown & Peer Comparison:** Full `T0` breakdown with **NIFTY 50 Alpha** and `Max/DD`, auto-matched **Sector Peer Comparison (Max 5)**, and **CSV export**.

### 2. IPO Report (SME & Regular / Mainboard — GMP-Free)
- **Live Indian IPO Screener:** Filter by Segment (`All`, `Regular`, `SME`), Exchange (`NSE`, `BSE`), Status (`Open`, `Allotment`, `Upcoming`, `Listed`), or name.
- **Analyze & Predict Modes:**
  - **Analyze:** One-click automated report on listed/active IPOs using NSE/SEBI/financial data.
  - **Predict:** Enter or customize RHP/financial inputs (Price, Lot Size, Issue Size, Fresh Issue %, Post-IPO EPS, 3-Year Revenue & PAT, Net Worth, Debt, QIB/NII/Retail subscription, NSE Peers) — or click **Load Example** to test immediately.
- **100-Point Scorecard & Verdicts:**
  - Overall **Score / 100**, direct **SEBI Filing** link (when available), and separate verdicts for **Listing Gains** and **Long Term**.
  - **Two-Tier Listing Price Estimate:** Fundamentals Only vs. Fundamentals + Demand (with per-lot gain).
  - **Price & Issue Split**, **Company Health**, **Buyers Demand (QIB / NII / Retail / Total)**, **What's Good**, **Risks to Watch**, **Yearly Sales & Profit/Loss (`₹ Cr`)** chart, and **Similar Listed Companies** comparison.

---

## Pages & Key Routes

- **`/`** — Introduction & Guide page (*What Is This · How to Use · What You Get · FAQ*)
- **`/app`** — Main VBP Research Analyzer (*Results & AGM* + *IPO Report*)
- **`/api/health`** — Health check endpoint
- **`/docs`** — FastAPI interactive API documentation

---

## Tech Stack

- **Backend:** Python 3.12, FastAPI, Uvicorn
- **Frontend:** HTML, Tailwind CSS (CDN), ECharts, Light & Dark theme support
- **Deployment:** Render Free (`render.yaml` Blueprint)

---

## Quick Start Locally (Windows)

Double-click **`run.bat`**, or run in PowerShell:

```powershell
.venv\Scripts\uvicorn.exe app.main:app --host 127.0.0.1 --port 8000 --reload
```

Then open **http://127.0.0.1:8000** in your browser.

### Run Tests

```powershell
.venv\Scripts\python.exe -m pytest tests -v
```

---

## Deploy Free on Render

1. Sign in at **https://dashboard.render.com** with GitHub.
2. Click **New → Blueprint** and select **`Bhargav8989/VBP-Research`**.
3. Render reads **`render.yaml`** (`plan: free`, health check `/api/health`) and deploys automatically on every push to `main`.

---

## Disclaimer & Contact

VBP Research is for **educational and informational purposes only** and is **not SEBI-registered investment advice**.

- Contact: **https://www.vbpventures.co.in/contact**
