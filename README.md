# 🏏 Cricket AI Broadcaster

A simple, single-server web app that turns a live CREX match page into:
- A live scoreboard + ball-by-ball feed in the browser.
- Spoken commentary — the **exact ball-by-ball text as published on the source site**, read aloud in a neural voice. Nothing is invented, rewritten, or padded with filler; only the delivery (pace/pitch) is nudged per event (wicket, six, four, dot ball) so it doesn't sound flat.
- An optional simultaneous push of the same commentary to **YouTube Live** over RTMP.

---

---

## ⚡ Step-by-Step Installation Guide (Beginner Friendly)

If you have never set up a Python project before, follow the steps below for your operating system. Every command can be copied and pasted directly into your terminal.

> [!TIP]
> **Don't want to install anything on your computer?**
> Use the **[Deploy to Render](#-deploy-to-render)** button below to run the app in the cloud 100% free with one click!

---

### 🍏 Mac & Linux Users

#### Step 1: Open Terminal
- **Mac**: Press `Cmd + Space`, type `Terminal`, and press Enter.
- **Linux**: Press `Ctrl + Alt + T`.

#### Step 2: Clone & open project folder
```bash
git clone https://github.com/raushan22882917/cricket.git
cd cricket
```

#### Step 3: Create and activate a virtual environment
```bash
python3 -m venv .venv
source .venv/bin/activate
```
*(You will see `(.venv)` appear at the beginning of your terminal prompt).*

#### Step 4: Install dependencies
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

#### Step 5: (Optional) Install FFmpeg
*Only needed if you plan to broadcast live to YouTube RTMP:*
- **Mac** (using [Homebrew](https://brew.sh)):
  ```bash
  brew install ffmpeg
  ```
- **Ubuntu / Debian Linux**:
  ```bash
  sudo apt update && sudo apt install -y ffmpeg
  ```

#### Step 6: Start the app
```bash
python3 server.py
```

#### Step 7: Open in your browser
Open your web browser (Chrome, Safari, Edge) and go to:
👉 **[http://localhost:8088](http://localhost:8088)**

---

### 🪟 Windows Users Guide

#### Option A: One-Click Launcher (Easiest for Non-Tech Users)
1. **Install Python**:
   - Download Python from [python.org/downloads](https://www.python.org/downloads/).
   - ⚠️ **CRITICAL**: During setup, check the box that says **"Add python.exe to PATH"** at the bottom of the installer window!
2. **Download the code**:
   - Click the green **Code** button at the top of this GitHub page -> click **Download ZIP**.
   - Extract the ZIP file anywhere on your computer.
3. **Double-click `run_windows.bat`**:
   - Just double-click the file named `run_windows.bat` in the project folder.
   - It will automatically set up the virtual environment, install packages, open your browser, and launch the app!

---

#### Option B: Manual Command-by-Command (PowerShell)

##### Step 1: Open PowerShell
- Press the `Windows key`, type `PowerShell`, and press Enter.

##### Step 2: Clone & enter project folder
```powershell
git clone https://github.com/raushan22882917/cricket.git
cd cricket
```
*(Or if you downloaded the ZIP, type `cd` followed by the folder path where you extracted it, e.g. `cd C:\Users\YourName\Downloads\cricket`).*

##### Step 3: Create virtual environment
```powershell
python -m venv .venv
```

##### Step 4: Activate virtual environment
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.venv\Scripts\Activate.ps1
```
*(You will see `(.venv)` appear at the start of your prompt line).*

##### Step 5: Install required dependencies
```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

##### Step 6: Start the server
```powershell
python server.py
```

##### Step 7: Open in your browser
Open Chrome, Edge, or Firefox and go to:
👉 **[http://localhost:8088](http://localhost:8088)**

---

#### 🛠️ Windows Troubleshooting & FAQs

- **Error: `'python' is not recognized as an internal or external command`**:
  - Re-run the Python installer, select **Modify**, and make sure **"Add Python to environment variables" / "Add python.exe to PATH"** is checked. Then restart PowerShell/CMD.
- **Error: `File ... Activate.ps1 cannot be loaded because running scripts is disabled`**:
  - Run this command in PowerShell first:
    ```powershell
    Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
    ```
    Then run `.venv\Scripts\Activate.ps1` again.
- **How to stop the server**:
  - Press `Ctrl + C` in the PowerShell or CMD window.

---

### 🐳 Docker Users (All Platforms)

If you already have [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed, you don't need Python or FFmpeg installed on your machine:

```bash
# 1. Build the Docker image
docker build -t cricket-broadcaster .

# 2. Run the container
docker run -p 8088:10000 cricket-broadcaster
```
Then open: **[http://localhost:8088](http://localhost:8088)**

---

## 🎮 How to Use the Web App

Once the web page is open in your browser:
1. **Choose a Match**:
   - Pick any ongoing game from the **Live Matches** dropdown list, or
   - Paste a link from CREX / Cricbuzz / ESPNcricinfo, or
   - Simply type team names (e.g. `India vs Australia`).
2. **Select Commentary Language**:
   - Choose **Hinglish AI (Recommended)** for dynamic, energetic Indian TV broadcast commentary (mix of Hindi + English), or pick **Hindi** / **English**.
3. **Select Voice Engine & AI Keys**:
   - **Edge-TTS**: 100% Free, no API key needed, natural neural voices.
   - **Sarvam AI**: Ultra-realistic Indian English / Hindi voices (enter your Sarvam key or set in `.env`).
   - **Gemini API Key**: Powers real-time context-aware Hinglish commentary (preconfigured in `.env` or editable in the UI).
4. **YouTube Live (Optional)**:
   - Paste your YouTube Live RTMP Stream Key if you also want to stream video + audio to YouTube.
5. Click **Start Broadcast** and listen to live ball-by-ball voice commentary!


## 🚀 Deploy to Render

Deploy this application directly to [Render](https://render.com) with full Docker, FFmpeg, and WebSocket support.

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy)

### Option 1: One-Click Blueprint (Recommended)
1. Push this repository to GitHub or GitLab.
2. Click the **Deploy to Render** button above (or go to [Render Dashboard](https://dashboard.render.com) -> **New +** -> **Blueprint**).
3. Connect your repository. Render will automatically read [`render.yaml`](render.yaml).
4. (Optional) Set `GEMINI_API_KEY` for Hinglish AI and `SARVAM_API_KEY` if you plan to use Sarvam AI Indic voices.
5. Click **Apply**. Render will build the Docker container (with FFmpeg and required fonts pre-installed) and launch the live web service.

### Option 2: Manual Web Service Setup
1. In the [Render Dashboard](https://dashboard.render.com), click **New +** -> **Web Service**.
2. Connect your repository.
3. Select **Docker** as the runtime.
4. Render will auto-detect the Dockerfile:
   - **Dockerfile Path**: `./Dockerfile`
   - **Health Check Path**: `/api/status`
   - **Port**: `10000` (Render defaults to `10000`)
5. Choose the **Free** plan and click **Create Web Service**.

---

## 🏗️ How it works

```
CREX match page
      │  (scraped every 1.5s)
      ▼
CrexParser.parse()  →  extracts all live ball text, matchup, bowler, striker & score
      │
      ▼
HumanCommentator  →  transforms all ball input into energetic Hinglish TV commentary
                      powered by Gemini AI (with fast local fallback)
      │
      ├──▶ Edge-TTS / Sarvam neural voice  →  streamed in-memory to the browser (WebSocket)
      │
      └──▶ CricketStreamingEngine  →  FFmpeg  →  YouTube Live RTMP (optional)
```

Everything runs from one process, `server.py`.

---

## 🎙️ Voice — real-time only, never saved

Each spoken line is synthesized in memory and sent straight to the browser as audio over the WebSocket. Nothing is ever written to disk — there is no recordings folder and no clip archive. While a broadcast is live but no new ball has landed yet, the UI shows a **"Waiting for next ball..."** indicator so it's clear the engine is still working, not stuck.

---

## ⚙️ Configuration (`.env`, optional)

| Variable | Default | Description |
|---|---|---|
| `PORT` | `8088` | Web server port |
| `HOST` | `0.0.0.0` | Web server bind address |
| `GEMINI_API_KEY` | *(empty)* | Google Gemini API key for live Hinglish commentary generation |
| `SARVAM_API_KEY` | *(empty)* | Optional Sarvam AI key for Bulbul voices |

The YouTube stream key, match language, and API keys can also be entered directly in the web UI when you start a broadcast.

---

## 📁 Project layout

- `server.py` — web server, WebSocket live feed, real-time voice streaming.
- `cricket_streamer.py` — CREX scraping/parsing, TTS, overlay rendering, YouTube RTMP streaming engine.
- `src/human_commentator.py` — takes all ball text as input and delivers lively Hinglish commentary.
- `web/` — browser UI.
