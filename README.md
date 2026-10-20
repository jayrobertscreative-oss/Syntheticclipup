# Synthetic Clip Up

**Create. Clip. Earn. Scale.** A clipping marketplace with a built-in AI Clip Studio, verified social
accounts, paid campaigns, free portfolio websites and a private Owner Control Centre.

The full plan, status of every feature and the phase order are in **[docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md)**.

## What runs today (Phase 1)

| URL | What it is | Status |
|---|---|---|
| `/` | Public homepage (hero, how it works, featured campaigns, Clip Studio, portfolio, verified accounts, analytics, fees, FAQ) | Built |
| `/campaigns`, `/clip-studio`, `/portfolio-builder`, `/how-it-works`, `/pricing`, `/legal` | Public pages | Built |
| `/sign-in`, `/get-started` | Account screens (Clipper or Campaign Manager; owner is never offered) | UI only — accounts arrive in Phase 2 |
| `/studio` | Clip Studio — the real clipping engine below (moved here from `/`) | Working |
| `/design` | Dashboard previews: clipper, campaign manager, Owner Control Centre, portfolio editor and public portfolio | Mockups with labelled demo data |
| `/api/fees/quote` | Server-side fee maths used by the pricing calculator and campaign form (no money moves) | Working, tested |

Honesty rules the site follows: live numbers (clips rendered, minutes processed) come from the real
database; marketplace numbers say "Opening soon" until real campaigns exist; every illustrative card
says **Example** and every dashboard preview carries a **Demo data** banner.

Set `SCU_DESIGN_PREVIEWS=0` to hide `/design` (e.g. once real dashboards exist).
Fee defaults (host 10%, clipper 5%) can be changed without code: `SCU_HOST_FEE_BPS`, `SCU_CLIPPER_FEE_BPS`,
`SCU_LAUNCH_FEE_MIN_MINOR`, `SCU_LAUNCH_FEE_MAX_MINOR` (basis points / cents). Phase 2 moves these into an owner-editable table.

### Code layout (new in Phase 1)

```
app/web.py          public pages, dashboard previews, fee-quote API
app/fees.py         authoritative fee & reward maths (integer cents, tested against every brief example)
app/demo.py         illustrative data for previews only — never read by engine or money code
app/templates/      Jinja2: base layout, UI macros (_ui.html), public/ and design/ pages
static/css/scu.css  design system (same tokens as the original dashboard)
static/js/site.js   menus, dashboard drawer, chart tooltips
tests/test_fees.py, tests/test_web.py
```

### Tests

```
python -m unittest discover -s tests -p "test_*.py"   # fees + every page and dashboard screen
python tests/smoke_test.py                            # clipping engine end to end (real FFmpeg)
```

---

## Clip Studio engine (the clipping backend)

Upload a video you own → FFmpeg extracts the audio → speech is transcribed with word timestamps →
Claude picks the best moments → FFmpeg renders real captioned MP4 clips → preview and download them.

## Why the old "Generate AI Clips" button did nothing

The dashboard you had is a Claude Artifact: one static HTML page in a locked-down sandbox.

- The button's handler only checked that the text looked like a link. It never called a server, because there was no server.
- An Artifact can't make network requests to other hosts, can't run FFmpeg, can't hold API keys safely, and can't store large files.
- So no Artifact can do this work. It needs a backend running on a server you control. This folder is that backend, and it serves the same dashboard.

## What's in here

```
synthetic-clip-up/
  app/
    main.py       HTTP API, signed media links, serves the web app
    worker.py     background worker that runs the processing jobs
    pipeline.py   the 9 stages (validate → … → completed)
    media.py      FFmpeg: probe, audio extraction, captions (.ass), rendering, thumbnails
    ai.py         speech-to-text (OpenAI) + highlight picks (Claude) + boundary snapping
    youtube.py    YouTube link parsing + official Data API v3 lookups
    db.py         SQLite: projects, jobs, job_events, transcripts, clips
    config.py     settings from environment / .env
  static/         the Synthetic Clip Up dashboard, now wired to the API
  tests/
    smoke_test.py end-to-end test (real FFmpeg + HTTP; AI calls stubbed)
    live_check.py checks your real API keys on one of your videos
  Dockerfile, start.sh, .env.example, requirements.txt
```

## Run it on your computer (Mac or Linux)

1. Install Python 3.11+ and FFmpeg (`brew install python ffmpeg` on a Mac).
2. In this folder:
   ```
   python3 -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   cp .env.example .env        # then paste your keys into .env
   ```
3. Start the two processes in two terminal tabs:
   ```
   uvicorn app.main:app --port 8000        # tab 1: website + API
   python -m app.worker                    # tab 2: processing worker
   ```
4. Open http://localhost:8000 (site) and http://localhost:8000/studio (Clip Studio)

### Your first real test

1. Open `/studio` → AI Auto Clipper → choose a ~5-minute MP4 you own with clear speech.
2. Pick 30 s, 3 clips, 9:16, Creator Bold, tick the rights box, press **Generate AI clips**.
3. The project page shows each stage as the worker reaches it. A 5-minute video usually finishes in 1–3 minutes.
4. Play each clip, then **Download MP4**.

If a stage fails, the page names the stage and the reason (missing key, no audio, provider error) and offers **Retry**.

Optional: `python tests/live_check.py my-video.mp4` checks both API keys in one go.

## Keys you need

| Service | Used for | Where |
|---|---|---|
| OpenAI API | Speech-to-text with word timings (`whisper-1`) | platform.openai.com |
| Anthropic API | Picking and ranking clips | console.anthropic.com |
| YouTube Data API v3 (optional) | Title, thumbnail, duration for pasted links | Google Cloud console |

Keys live only in `.env` on the server.

## YouTube links: what works and what doesn't

- **Works:** watch, youtu.be, /shorts/, mobile and embed links are parsed. With a YouTube key, the app shows the title, channel, thumbnail, length and whether the video is publicly available.
- **Does not work, by design:** clipping straight from a link. YouTube's official API gives details about a video, not the video file. Downloading the file would mean scraping, which breaks YouTube's terms. The app says this plainly and sends people to upload their original file. For their own channel, they can download it from YouTube Studio.
- **Later option:** with OAuth "Sign in with YouTube", the API can return caption tracks for videos on channels the user manages. That gives a transcript but still no video file, so upload remains the route for rendering.

## Putting it online

It needs a server with FFmpeg, a persistent disk, and the ability to run a long background process. Serverless hosting (Vercel, Netlify) won't work for the worker.

- **Easiest:** Railway or Fly.io. Deploy the `Dockerfile`, attach a volume at `/data`, and set the keys as environment variables. `start.sh` runs the website and one worker together.
- **Cheapest at scale:** a VPS (Hetzner, DigitalOcean) with `docker run -p 8000:8000 -v scu-data:/data --env-file .env scu`, behind Caddy for HTTPS.
- Set `SCU_SECRET`. Until accounts arrive in Phase 2, also set `SCU_ACCESS_KEY` so only you can use the site.

## What running costs depend on

- **Minutes of video transcribed.** This is the main per-video cost.
- **Transcript length sent to Claude.** One call per video, small compared with transcription.
- **Render CPU.** About 2–4× real time per clip on a small server. More workers means faster queues.
- **Storage and bandwidth.** Source uploads are large. Delete sources after N days in Phase 2.

## Known limits in this stage

- One user, no accounts yet (Phase 2). Credits and plans are Phase 5.
- SQLite + one worker on one machine. Moving to Postgres and a Redis queue is a later swap.
- Centre crop or padding only. Face tracking is Phase 6.
- Captions are burned in at render. Editing them afterwards needs the Phase 4 editor.
- Transcription audio is split into 20-minute parts, so very long videos take several calls.

## Tests

`python tests/smoke_test.py` makes a 5-minute video, uploads it over HTTP, runs every stage with real FFmpeg,
and checks the 3 clips are 1080×1920 MP4s with audio that stream (HTTP 206) and download. Only the two paid AI
responses are stubbed, because they need your keys.
