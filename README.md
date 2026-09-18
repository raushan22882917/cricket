# 🏏 Real-Time Cricket YouTube Live AI Broadcast Engine

An end-to-end automated broadcasting pipeline that transforms raw ball-by-ball cricket data into a television-style live stream on YouTube Live with:
- **Natural-Sounding, Monetisable Voice-Over**: Broadcast-engineered neural voice commentary (Ravi Shastri / Nasser Hussain / Ricky Ponting style).
- **Pure Color Commentary NLP**: Context-aware tactical insights, player career records, match pressure calculations, and historical cricket heritage (play-by-play left to graphics).
- **Dynamic 720p/1080p TV Broadcast Overlay**: Animated lower-third scoreboard, batsman/bowler cards, DRS/boundary/wicket flash banners, and live "On Air" commentary badge.
- **Sub-5-Second Latency**: Optimized asynchronous event-to-voice and FFmpeg RTMP zero-latency push directly to YouTube Live.
- **Single-Command Launch**: Automated startup with seamless fallback between Live YouTube streaming and local MP4 preview recording.

---

## ⚡ Quick Start (Single Command)

### 1. Run Local Broadcast Preview (No Stream Key Required)
```bash
./run_broadcast.sh --duration 30
```
This generates `broadcast_output.mp4` with full synced video, television overlay, crowd audio, and live AI commentary.

### 2. Stream Directly to YouTube Live
1. Open [YouTube Studio Live](https://studio.youtube.com) and click **Go Live**.
2. Copy your **Stream Key**.
3. Launch with:
```bash
./run_broadcast.sh --mode youtube --key YOUR_YOUTUBE_STREAM_KEY
```
Or add `YOUTUBE_STREAM_KEY=YOUR_KEY` inside `.env` and run:
```bash
./run_broadcast.sh --mode youtube
```

---

## 🏗️ System Architecture

```
[Live Ball Data Feed / Event Detector]
                   │
                   ▼ (JSON POST to http://localhost:8088/event)
      [Event Ingest & Match State]
         │                     │
         ▼                     ▼
[Color Commentary Engine]   [Broadcast Overlay Renderer]
 (Player Stats + Heritage)   (TV Lower-Third, Alerts, Pitch Radar)
         │                               │
         ▼                               ▼
 [Neural TTS Broadcaster]           [Raw RGB Video]
         │                               │
         ▼                               ▼
 [Stadium Audio Mixer] ─────────────▶ [FFmpeg RTMP Pipeline]
                                         │
                                         ▼
                             [YouTube Live Dashboard]
```

---

## 🎙️ NLP Commentary & Voice Broadcaster

### Color Commentary Engine (`src/commentary_engine.py`)
Unlike standard play-by-play (which simply announces "Cummins bowls to Kohli, four runs"), this engine produces **pure color commentary**:
- **Player Stats & Signatures**: References Kohli's 88+ average in T20 chases, Rohit's world record sixes, Bumrah's hyperextended release point.
- **Tactical Analysis**: Highlights field placements (deep point, backward square), bowling seam presentation, and bowler speeds.
- **Cricket Heritage**: Evokes iconic moments (e.g. Kohli's 2022 MCG straight six), venue idiosyncrasies (Wankhede's short boundaries & evening dew).
- **Dual Engine**:
  - **Gemini 2.5 Flash (`google-genai`)**: Generates real-time, high-creativity color banter if `GEMINI_API_KEY` is provided.
  - **Heuristic Neural Narrative Engine**: Built-in zero-latency engine operating with sub-50ms execution and 100% cricket accuracy.

### Neural TTS Engine (`src/tts_engine.py`)
- **Voices Available**:
  - `en-IN-PrabhatNeural`: Authoritative Indian English commentator (Ravi Shastri tone).
  - `en-IN-NeerjaNeural`: Insightful female broadcaster (Isa Guha tone).
  - `en-GB-RyanNeural`: British cricket analyst (Nasser Hussain / Michael Atherton tone).
  - `en-AU-WilliamNeural`: Australian fast-paced color commentator (Ricky Ponting tone).
- **Acoustic Staging**: Broadcast presence EQ boost, gentle bass warmth, and studio normalization ensure voice uniqueness and YouTube monetization compliance.

---

## 📡 Live Ingestion API (Event Webhook)

You can push live ball events from your event detector into the engine via HTTP POST:

```bash
curl -X POST http://localhost:8088/event \
  -H "Content-Type: application/json" \
  -d '{
    "match_id": "IND_AUS_T20_2026",
    "match_title": "India vs Australia - 3rd T20I",
    "venue": "Wankhede Stadium",
    "innings": 2,
    "batting_team": "IND",
    "bowling_team": "AUS",
    "target": 188,
    "over": 18,
    "ball": 1,
    "runs": 4,
    "is_boundary": true,
    "boundary_type": 4,
    "is_wicket": false,
    "striker": "Virat Kohli",
    "striker_runs": 48,
    "striker_balls": 34,
    "non_striker": "Hardik Pandya",
    "non_striker_runs": 24,
    "non_striker_balls": 14,
    "bowler": "Pat Cummins",
    "bowler_overs": 3.1,
    "bowler_runs": 28,
    "bowler_wickets": 1,
    "total_runs": 168,
    "total_wickets": 4,
    "play_by_play": "Cummins pitches up outside off, Kohli leans into a majestic cover drive for four.",
    "speed_kph": 139.4
  }'
```

---

## ⚙️ Configuration (`.env`)

| Variable | Default | Description |
|---|---|---|
| `STREAM_MODE` | `preview` | `youtube`, `preview`, or `rtmp` |
| `YOUTUBE_STREAM_KEY` | `""` | Your YouTube Live stream key |
| `TTS_VOICE` | `en-IN-PrabhatNeural` | Edge-TTS neural voice model |
| `COMMENTARY_MODE` | `auto` | `auto`, `gemini`, or `offline` |
| `GEMINI_API_KEY` | `""` | (Optional) Google Gemini API key |
| `VIDEO_WIDTH` / `HEIGHT` | `1280` / `720` | Broadcast resolution |
| `VIDEO_FPS` | `30` | Broadcast framerate |
| `EVENT_SERVER_PORT` | `8088` | Webhook ingestion port |

