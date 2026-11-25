# VBP Research — Indian Stock & IPO Analyzer

A lightweight web application for analyzing Indian stocks (NSE/BSE) around **Quarterly Results**, **AGM**, or **Custom Dates**, plus a **GMP-Free SME & Regular IPO Fundamental & Valuation Report**.

## Publish Free on Hugging Face Spaces (No Domain / Server Needed)
1. Create a free account at **https://huggingface.co/spaces** and click **Create new Space**.
2. Choose **Space SDK: Docker** (Blank) and set visibility to **Public**.
3. Upload the files from this folder (or push via Git) — Hugging Face will automatically build and give you a free public link anyone can open.

## Quick Start Locally (Windows)
Double-click **`run.bat`**, or run in PowerShell:

```powershell
.venv\Scripts\uvicorn.exe app.main:app --host 127.0.0.1 --port 8000 --reload
```

Then open **http://127.0.0.1:8000** in your browser.
