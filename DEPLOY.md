# Deployment Guide (Render or Railway)

This app is designed to be easily deployable on free-tier hosting platforms like Render or Railway. 
The instructions below focus on Render.

## Prerequisites
1. Create a GitHub repository and push this code to it.
2. Sign up for a [Render](https://render.com) account.

## Steps for Render
1. Go to your Render Dashboard and click **New+** -> **Web Service**.
2. Connect your GitHub account and select the repository containing this code.
3. Configure the following settings for the web service:
   - **Name**: `live-polling-app` (or your choice)
   - **Environment**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn app:app`
   - **Instance Type**: `Free`
4. Click **Create Web Service**.
5. Render will now build and deploy your app. Once finished, you'll see a public URL (e.g., `https://live-polling-app.onrender.com`).

## Important Notes for Free Tier

### 1. Ephemeral Filesystem (Data Reset)
On Render and Railway free tiers, the filesystem is **ephemeral**. This means every time the service restarts or redeploys, all files are reset to their original state in the Git repository. 
Because this app uses a single SQLite file (`poll.db`) for simplicity, **all votes and polling data will be lost upon restart or redeploy**.
*This is perfectly fine for a single live event*, provided you do not trigger a manual deploy or restart mid-show.

### 2. Cold Starts (Sleeping)
Free tier services on Render will "sleep" after a period of inactivity (typically 15 minutes). 
When a service is asleep, the first request it receives will wake it up, but this process can take **30 to 50 seconds**. 
**Recommendation:** About 5-10 minutes before your event starts, open the app's URL and click around to ensure the service is awake and responsive *before* the audience scans the QR code.
