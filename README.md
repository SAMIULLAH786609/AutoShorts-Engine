# AutoShorts Engine

**A fully automated AI-powered YouTube Shorts creation and publishing system.**

After one-time API configuration, the engine runs completely on its own:
- Discovers worldwide trending topics from 6+ sources
- Generates original scripts with Google Gemini AI
- Creates AI narration with Microsoft Edge TTS
- Downloads copyright-safe stock videos (Pexels, Pixabay)
- Renders professional Shorts with animated subtitles
- Generates branded thumbnails
- Uploads to YouTube (private by default)
- Prevents duplicate content with a SQLite history database
- Schedules itself to run automatically 2× per day

---

## Table of Contents

1. [Project Structure](#project-structure)
2. [Quick Start](#quick-start)
3. [API Setup](#api-setup)
4. [Configuration](#configuration)
5. [How to Run](#how-to-run)
6. [Scheduling](#scheduling)
7. [Deployment (Cloud)](#deployment-cloud)
8. [Project Architecture](#project-architecture)
9. [Troubleshooting](#troubleshooting)

---

## Project Structure

```
AutoShorts-Engine/
│
├── run.py                    ← SINGLE ENTRY POINT: python run.py
├── config.py                 ← All configuration (reads from .env)
├── make_video.py             ← MoviePy renderer (library)
│
├── autoshorts/
│   ├── models.py             ← Data models (VideoPlan, TrendItem, etc.)
│   ├── pipeline.py           ← Full automated pipeline (12 steps)
│   ├── scheduler.py          ← APScheduler daemon (twice-daily)
│   └── services/
│       ├── trend_sources.py  ← 6-source trend collector
│       ├── gemini_service.py ← AI: topic ideas, research, scripts
│       ├── voice_service.py  ← Edge-TTS narration generator
│       ├── video_collector.py← Pexels + Pixabay downloader
│       ├── renderer.py       ← Professional Short video renderer
│       ├── thumbnail_generator.py ← Pillow thumbnail creator
│       ├── history_db.py     ← SQLite dedup + history
│       ├── youtube_upload.py ← OAuth YouTube upload (unchanged)
│       └── logging_setup.py  ← Structured logging
│
├── credentials/
│   ├── client_secret.json    ← Download from Google Cloud Console
│   └── youtube_token.json    ← Auto-created after first OAuth login
│
├── data/
│   └── autoshorts.db         ← SQLite database
│
├── output/                   ← Final MP4 files
├── downloads/                ← Temporary scene clips (auto-cleaned)
├── thumbnails/               ← Generated JPEG thumbnails
├── metadata/                 ← JSON content plans
├── logs/
│   └── autoshorts.log        ← Full pipeline logs
├── music/                    ← Optional background music (MP3/WAV)
├── cache/                    ← API response cache (speeds up repeats)
│
├── .env                      ← Your API keys (gitignored)
├── .env.example              ← Config template
├── requirements.txt
└── run_twice_daily.bat       ← Windows Task Scheduler trigger
```

---

## Quick Start

### 1. Clone / navigate to the project

```bash
cd AutoShorts-Engine
```

### 2. Create and activate a virtual environment

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/Mac:
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure your API keys

```bash
copy .env.example .env
```

Open `.env` and fill in your keys (see [API Setup](#api-setup) below).

### 5. Run

```bash
python run.py
```

That's it. The system will automatically find a trend, write a script, generate a voice, download videos, render a Short, and upload it to YouTube as **Private**.

---

## API Setup

### Required

#### Google Gemini API
- Visit: https://aistudio.google.com/app/apikey
- Create an API key
- Add to `.env`: `GEMINI_API_KEY=your_key`

#### Pexels API
- Visit: https://www.pexels.com/api/
- Register a free account and create an API key
- Add to `.env`: `PEXELS_API_KEY=your_key`

#### YouTube Data API v3 + OAuth
This is needed for **both** trend discovery AND video upload.

**Step 1:** Enable the API
- Go to: https://console.cloud.google.com
- Create a project
- Search for "YouTube Data API v3" → Enable it

**Step 2:** Create OAuth credentials (for upload)
- APIs & Services → Credentials → Create Credentials → OAuth 2.0 Client ID
- Application type: **Desktop app**
- Download the JSON file
- Rename it to `client_secret.json`
- Place it in: `credentials/client_secret.json`

**Step 3:** Create an API Key (for trend discovery)
- APIs & Services → Credentials → Create Credentials → API Key
- Add to `.env`: `YOUTUBE_API_KEY=your_key`

> **First run:** A browser window will open for OAuth consent. Login with your YouTube account. The token is saved to `credentials/youtube_token.json` and reused automatically after that.

### Optional

#### Pixabay API (fallback video source)
- Visit: https://pixabay.com/api/docs/
- Free API key available after registration
- Add to `.env`: `PIXABAY_API_KEY=your_key`

#### NewsAPI (additional news trends)
- Visit: https://newsapi.org/
- Free tier: 100 requests/day
- Add to `.env`: `NEWS_API_KEY=your_key`

---

## Configuration

All settings live in `.env`. Key settings:

| Variable | Default | Description |
|---|---|---|
| `CHANNEL_NICHE` | `Interesting facts and viral stories` | Gemini uses this to generate relevant topics |
| `REGION_CODE` | `US` | Primary region for YouTube trends |
| `DAILY_VIDEO_COUNT` | `2` | Videos per scheduled run |
| `DEFAULT_PRIVACY` | `private` | `private` / `unlisted` / `public` |
| `UPLOAD_TIME_1` | `10:00` | First daily upload time (24h) |
| `UPLOAD_TIME_2` | `18:00` | Second daily upload time (24h) |
| `GEMINI_MODEL` | `gemini-2.0-flash` | Gemini model (auto-fallback on failure) |
| `DEFAULT_GENDER` | `female` | Default voice gender |
| `TREND_REGIONS` | `US,GB,CA,AU,...` | Regions for YouTube trend collection |

---

## How to Run

### Run once now (produce today's videos immediately)

```bash
python run.py
```

### Run exactly N videos

```bash
python run.py --count 1
```

### Start the always-on scheduler daemon

```bash
python run.py --schedule
```

This starts a blocking process that runs at `UPLOAD_TIME_1` and `UPLOAD_TIME_2` every day.

---

## Scheduling

### Option A: Windows Task Scheduler (recommended for Windows)

1. Open **Task Scheduler**
2. Create a Basic Task
3. Set trigger: **Daily** at your preferred time
4. Action: Start a program
   - Program: `C:\Users\<you>\OneDrive\Desktop\AutoShorts-Engine\.venv\Scripts\python.exe`
   - Arguments: `run.py`
   - Start in: `C:\Users\<you>\OneDrive\Desktop\AutoShorts-Engine`

Or use the provided `.bat` file:
- Right-click `run_twice_daily.bat` → **Run as administrator**

### Option B: APScheduler daemon (for cloud/Linux)

```bash
python run.py --schedule
```

Keep this running with `nohup`, `screen`, `tmux`, or a `systemd` service.

---

## Deployment (Cloud)

### Railway / Render / Fly.io

1. Push the repo to GitHub (make sure `.env` is in `.gitignore`)
2. Connect repo to your cloud provider
3. Set environment variables in the cloud dashboard (same as `.env`)
4. Set start command: `python run.py --schedule`
5. Add `credentials/client_secret.json` as a secret file

### Docker

A `Dockerfile` for containerized deployment:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    ffmpeg \
    libgl1-mesa-glx \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV FONT_PATH=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf

CMD ["python", "run.py", "--schedule"]
```

Build and run:

```bash
docker build -t autoshorts .
docker run -d \
  --env-file .env \
  -v $(pwd)/credentials:/app/credentials \
  -v $(pwd)/output:/app/output \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/logs:/app/logs \
  autoshorts
```

### DigitalOcean VPS / AWS EC2

```bash
# Install system deps
sudo apt install python3-pip python3-venv ffmpeg -y

# Clone repo and setup
git clone <your-repo-url> autoshorts
cd autoshorts
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Configure
cp .env.example .env
nano .env   # fill in your keys

# Run as a systemd service
sudo nano /etc/systemd/system/autoshorts.service
```

`/etc/systemd/system/autoshorts.service`:
```ini
[Unit]
Description=AutoShorts Engine
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/autoshorts
ExecStart=/home/ubuntu/autoshorts/.venv/bin/python run.py --schedule
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable autoshorts
sudo systemctl start autoshorts
sudo journalctl -u autoshorts -f   # view logs
```

---

## Project Architecture

```
Scheduler (APScheduler or cron)
         │
         ▼
  run_pipeline()           ← autoshorts/pipeline.py
         │
         ├─ collect_worldwide_trends()     ← 6 sources: YouTube, GDELT, RSS, Reddit, HN, NewsAPI
         │
         ├─ generate_topic_ideas()         ← Gemini: 10 original ideas, scored + deduped
         │
         ├─ topic_exists()                 ← SQLite dedup check
         │
         ├─ research_topic()               ← Gemini: fact research & summarization
         │
         ├─ generate_video_plan()          ← Gemini: script + SEO + voice + visual keywords
         │
         ├─ generate_voice()               ← Edge-TTS: MP3 narration
         │
         ├─ collect_scene_videos()         ← Pexels → Pixabay fallback, with URL caching
         │
         ├─ render_short()                 ← MoviePy: background + subtitles + music
         │
         ├─ generate_thumbnail()           ← Pillow: branded JPEG thumbnail
         │
         ├─ upload_video()                 ← YouTube Data API v3 (OAuth)
         │
         └─ mark_video_uploaded()          ← SQLite: full metadata saved
```

---

## Troubleshooting

### "GEMINI_API_KEY is missing"
Add your Gemini API key to `.env`.

### "No stock videos downloaded"
- Check `PEXELS_API_KEY` is set correctly
- Pexels free tier has rate limits — add `PIXABAY_API_KEY` as a fallback

### "client_secret.json not found"
Download OAuth credentials from Google Cloud Console and place at `credentials/client_secret.json`.

### "YouTube API returned 403"
- Ensure **YouTube Data API v3** is enabled in Google Cloud Console
- Check your API key quota

### "All Gemini models failed"
Your Gemini API key may have hit its quota. Check https://aistudio.google.com/. Free tier has generous limits; try again in a few minutes.

### Videos look stretched or wrong orientation
Ensure your Pexels API key is working. The downloader specifically requests portrait orientation.

### Subtitles not visible
The font at `FONT_PATH` may not exist on your system. On Linux, set:
```
FONT_PATH=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf
```

### Scheduler not running
Run `python run.py --schedule` in a persistent terminal session (use `screen` or `tmux` on Linux).

---

## Logs

All pipeline activity is logged to `logs/autoshorts.log`:

```
2026-07-16 10:00:01 | INFO     | TREND DISCOVERY — Collecting worldwide trends…
2026-07-16 10:00:08 | INFO     | Total trend signals: 247
2026-07-16 10:00:08 | INFO     | TOPIC SELECTION — Generating and scoring original ideas…
2026-07-16 10:00:15 | INFO     | Selected topic: 'Why Deep Sea Fish Glow in the Dark'
2026-07-16 10:00:15 | INFO     | RESEARCH — Researching topic…
2026-07-16 10:00:21 | INFO     | SCRIPT GENERATION — Writing original script…
2026-07-16 10:00:28 | INFO     | VOICE GENERATION — Voice: en-US-AriaNeural
2026-07-16 10:00:31 | INFO     | VIDEO COLLECTION — Downloading copyright-safe clips…
2026-07-16 10:01:02 | INFO     | RENDERING — Output: Why_Deep_Sea_Fish_Glow.mp4
2026-07-16 10:03:44 | INFO     | THUMBNAIL — Generating thumbnail…
2026-07-16 10:03:45 | INFO     | UPLOAD — Uploading to YouTube (private)…
2026-07-16 10:04:10 | INFO     | Upload successful! Video ID: abc123XYZ
2026-07-16 10:04:11 | INFO     | DATABASE — Saving metadata…
2026-07-16 10:04:11 | INFO     | PIPELINE COMPLETE — Video ID: abc123XYZ
```

---

## Adding Background Music

Place royalty-free `.mp3` or `.wav` files in the `music/` folder.
The renderer will automatically pick a random track and mix it at 8% volume under the narration.

Free royalty-free music sources:
- https://pixabay.com/music/
- https://freemusicarchive.org/
- https://incompetech.com/

---

*Built with ❤️ using Google Gemini, Edge-TTS, MoviePy, and the YouTube Data API.*
