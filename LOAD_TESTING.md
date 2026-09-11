# Load Testing the Live Polling App

## Overview

`load_test.py` is a standalone asyncio script that simulates a realistic crowd of attendees — each with a unique device UUID, sustained polling, and a burst vote — against the **deployed** instance of the app.

> **Important:** Only run this against your own deployed instance. Never run it against someone else's service. Running 300 concurrent polling clients for 3 minutes against a shared service is a denial-of-service attack.

---

## Setup

Install the dev dependency (do **not** add this to `requirements.txt`):

```bash
pip install -r requirements-dev.txt
```

---

## Usage

```bash
python load_test.py --url https://YOUR-APP-NAME.onrender.com [options]
```

`--url` is **required** and has no default, so the script can never silently hit the wrong target.

---

## Flags

| Flag | Default | Description |
|---|---|---|
| `--url` | *(required)* | Full public URL of the deployed app, e.g. `https://your-app.onrender.com`. |
| `--voters` | `300` | Number of virtual voters to simulate. Each gets its own unique UUID. |
| `--poll-interval` | `4.0` | How often (in seconds) each voter polls `/api/voter/current`, mimicking a real open browser tab. |
| `--duration` | `180` | Total test duration in seconds. 180s (3 min) is the default because sustained polling is the primary load — votes complete in the first few seconds regardless. |

---

## What it does

1. **Warms up the instance** — Sends a single GET request and retries until the Render instance wakes up (free tier sleeps after inactivity; wake can take 30–50s). Timing starts **after** the instance is confirmed awake.
2. **Spawns N virtual voters concurrently**, each:
   - Generates a unique `voter_id` UUID (same as a real device's `localStorage`).
   - Polls `GET /api/voter/current` every `--poll-interval` seconds for `--duration` seconds.
   - Casts exactly one `POST /vote` at a random moment in the first 0.5–5s (the realistic burst window).
3. **Writes a raw log** to `load_test_results.csv` with every request's timestamp, endpoint, latency, HTTP status, and success flag.

---

## Output

After the test, the script prints:

```
--- Load Test Results ---

Polling (GET /api/voter/current):
  Total requests: <N>
  Errors/Timeouts: <N> (<N.N>%)
  Latency: Min=Xms | Avg=Xms | p95=Xms | p99=Xms | Max=Xms

Voting (POST /vote):
  Total requests: <N>
  Errors/Timeouts: <N> (<N.N>%)
  Latency: Min=Xms | Avg=Xms | p95=Xms | p99=Xms | Max=Xms

Peak RPS (burst window, first 10s): <N>
Peak RPS (sustained window): <N>
Overall Success Rate: <N.NN>%

Verdict: Looks solid
  -- OR --
Verdict: WARNING - Failed on <metric(s)>
```

**Verdict passes** ("Looks solid") if:
- Overall success rate > 99%, **and**
- p95 latency < 1000ms for both polling and voting.

Otherwise it names which metric(s) failed.

---

## Interpreting results

| Metric | What to look for |
|---|---|
| **Success rate** | Should be >99%. Errors below this indicate the app or DB is struggling under load. |
| **p95 / p99 polling latency** | The floor of the live-event experience. If p95 > ~500ms, voters notice lag. Over 1s is a problem. |
| **p95 / p99 vote latency** | Vote submissions tolerate a bit more latency than polling, but consistent >2s is bad UX. |
| **Peak RPS (burst)** | Expected to be high (up to `voters` / 4 per second for polls, plus votes). This is the stress spike. |
| **Peak RPS (sustained)** | Should be roughly `voters / poll_interval`. If it drops significantly, some tasks are timing out. |

---

## Tips

- Run the test **5–10 minutes before your event starts** to confirm the Render instance is healthy under load — not 5 minutes before your QR code goes live.
- After the test, check `load_test_results.csv` for any error spikes at specific timestamps (e.g. correlated with the vote burst).
- On Render's **free tier with a single gunicorn worker**, the expected ceiling is roughly 50–150 concurrent requests before SQLite WAL contention shows up in latency. 300 voters polling every 4 seconds = 75 RPS sustained, which should be fine.
