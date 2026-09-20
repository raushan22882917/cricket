# 🏏 Cricket AI Broadcaster

A simple, single-server web app that turns a live CREX match page into:
- A live scoreboard + ball-by-ball feed in the browser.
- Spoken commentary — the **exact ball-by-ball text as published on the source site**, read aloud in a neural voice. Nothing is invented, rewritten, or padded with filler; only the delivery (pace/pitch) is nudged per event (wicket, six, four, dot ball) so it doesn't sound flat.
- An optional simultaneous push of the same commentary to **YouTube Live** over RTMP.

---

## ⚡ Quick Start

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python server.py
```

Open `http://localhost:8088`, then:
1. Pick a live match from the dropdown, or paste any CREX/Cricbuzz/Cricinfo match link (or just type team names).
2. Choose the commentary language (English / Hindi).
3. Optionally paste a YouTube Live RTMP stream key to broadcast there at the same time.
4. Click **Start**.

---

## 🚀 Deploy to Render

Deploy this application directly to [Render](https://render.com) with full Docker, FFmpeg, and WebSocket support.

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy)

### Option 1: One-Click Blueprint (Recommended)
1. Push this repository to GitHub or GitLab.
2. Click the **Deploy to Render** button above (or go to [Render Dashboard](https://dashboard.render.com) -> **New +** -> **Blueprint**).
3. Connect your repository. Render will automatically read [`render.yaml`](render.yaml).
4. (Optional) Set `SARVAM_API_KEY` if you plan to use Sarvam AI Indic voices.
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
CrexParser.parse()  →  real ball-by-ball commentary text only
      │
      ▼
HumanCommentator  →  classifies each ball (wicket/six/four/dot) for voice tone,
                      speaks the source text unchanged
      │
      ├──▶ Edge-TTS neural voice  →  streamed in-memory to the browser (WebSocket)
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

The YouTube stream key and match language are entered in the web UI when you start a broadcast, not in `.env`.

---

## 📁 Project layout

- `server.py` — web server, WebSocket live feed, real-time voice streaming.
- `cricket_streamer.py` — CREX scraping/parsing, TTS, overlay rendering, YouTube RTMP streaming engine.
- `src/human_commentator.py` — classifies each ball for voice tone; never rewrites the source text.
- `web/` — browser UI.
