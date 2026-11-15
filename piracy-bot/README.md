# PIRACY stats bot

Runs on GitHub Actions every 3 hours, for free, and keeps a Discord channel up to date:

- **New video alerts** when a clip appears on YouTube Shorts, Instagram Reels or in the TikTok sheet.
- **24-hour and 7-day check-ins** for every clip, compared with your usual numbers at the same age.
- **"Taking off" alerts** when a clip is beating your usual by 2× or more, so you can jump on it.
- **A live scoreboard**: one message the bot keeps editing. Pin it.
- **A tab for each app** (optional): TikTok, YouTube Shorts and Instagram Reels each get their own
  page in a Discord forum channel, linked from the scoreboard.
- **A Monday report** with what changed, **what to do next**, and **what's working in other
  Roblox dev Shorts** right now.
- **data/posts.json** in the analytics dashboard's format, so Claude can refresh the dashboard from it.

Changes are marked 🟢 up, 🔴 down and 🆕 new, which show the same on desktop and phones.

| Where | How it's read | Setup |
| --- | --- | --- |
| YouTube Shorts | Automatically, with a free API key | Step 2 |
| Instagram Reels | Automatically, once you add a token | Step 4 (optional) |
| TikTok | Typed into `manual/posts.csv` | Step 5 |
| Discord members | Automatically, from an invite code | Step 3 |

TikTok only lets outside tools read stats through apps it approves, so TikTok numbers are typed in
for now. Editing the file takes a minute, or send Claude the analytics screenshot and it will give
you the line to paste.

## Setup (about 20 minutes, all free)

1. **Put it on GitHub.** Make a **private** repo (or use the trend bot's). Add file → Upload files,
   and drag in the `piracy-bot` and `.github` folders. If you added the earlier `piracy-stats` kit,
   delete it: this replaces it.

2. **YouTube key.**
   - Go to console.cloud.google.com and create a project (e.g. "PIRACY stats").
   - APIs & Services → Library → **YouTube Data API v3** → Enable.
   - APIs & Services → Credentials → Create credentials → **API key**. Edit the key and restrict it
     to YouTube Data API v3.
   - In the GitHub repo: Settings → Secrets and variables → Actions → New repository secret,
     name `YOUTUBE_API_KEY`.
   - Edit `piracy-bot/config.json` and replace `@YOUR_YOUTUBE_HANDLE` with PIRACY's YouTube handle.

3. **Discord.**
   - New repository secret `DISCORD_STATS_WEBHOOK` = the webhook URL.
   - For the member count, put a permanent invite code (the part after `discord.gg/`) in
     `config.json` → `discord` → `invite_code`.

4. **Instagram (optional).**
   - In the Instagram app, switch PIRACY to a professional (Creator) account.
   - At developers.facebook.com, create an app with the Instagram use case. Under "API setup with
     Instagram login", add the PIRACY account and generate an access token.
   - New repository secret `INSTAGRAM_TOKEN`.
   - Tokens last 60 days. The bot warns you on the scoreboard before it runs out. To have it renew
     the token itself, add a secret `GH_SECRETS_PAT`: a fine-grained GitHub token for this repo
     with **Secrets: Read and write**.

5. **TikTok numbers.** Open `piracy-bot/manual/posts.csv` on GitHub, press the pencil, add a line,
   and Commit. The bot runs straight away. One line per post; update the same line later with the
   24-hour and then 7-day numbers and change `numbers_from` to match.

   ```
   platform,posted,title,video_id,format,views,likes,comments,shares,saves,follows,avg_watch_s,full_watch_pct,numbers_from,link,duration_s
   TikTok,2026-11-18 18:00,Storm battle,,Gameplay,1240,96,14,31,22,41,8.5,21%,24 h,https://www.tiktok.com/@piracy/video/123,24
   ```
   - `posted` is UK time. `video_id` can be left blank: the bot matches it to the same clip on the
     other apps.
   - `numbers_from` says when you took the numbers (`24 h`, `7 days`); check-ins use it.

6. **Start it.** Actions tab → **PIRACY stats bot** → Run workflow. It posts a "Stats bot is live"
   message, the first report and the scoreboard. **Pin the scoreboard.** From then on it runs by
   itself every 3 hours.

**Optional, a tab for each app:** create a **Forum** channel (for example `#stats-by-app`), then
Edit Channel → Integrations → Webhooks → New Webhook → Copy Webhook URL. Add it as the secret
`DISCORD_TABS_WEBHOOK`. On its next run the bot creates three posts in that forum (TikTok, YouTube
Shorts, Instagram Reels), keeps them up to date, and links them from the scoreboard. Leave "Require
tags" off in the forum's settings. If you delete a post, the bot makes a new one.

**Optional, Discord joins per invite link:** in the Discord Developer Portal create an application
→ Bot → Reset Token and copy it. Invite the bot to the server with the **Manage Server** permission
(Discord requires it to read invite counts). Add the secret `DISCORD_BOT_TOKEN`, and name your invite
codes in `config.json`, e.g. `"invite_names": {"abc123": "TikTok bio"}`. The scoreboard then shows
joins per link for the past week.

## How it decides things

- **Same clip on different apps:** posts within 3 days of each other with similar titles become one
  video (V00, V01, ...). Fix a wrong match in `manual/links.csv`.
- **Format:** guessed from the title (cutscene, cinematic, trailer → Cinematic; battle, storm,
  gameplay → Gameplay; devlog, update → Devlog). Set it yourself in the `format` column.
- **"Your usual":** the middle value of your other posts on that app at the same age. It needs
  3 earlier posts on the app before it compares.
- **Private or deleted videos** simply stop counting. They never show up as a drop, and the scoreboard
  says once how many went.
- **Recommendations** only appear once there's enough data (for example 3 gameplay and 3
  cinematic posts before it says which works better).
- **Other devs' Shorts:** once a day it searches YouTube for recent Roblox dev Shorts (search words
  in `config.json` → `scanner` → `queries`) and ranks them by views per day. TikTok can't be scanned
  automatically.

## Other bits

- `python piracy-bot/selftest.py` rehearses a week with fake numbers and checks the messages.
  Nothing is sent.
- Without `DISCORD_STATS_WEBHOOK` (or with `DRY_RUN=1`) the bot writes its messages to
  `data/outbox.json` instead of posting.
- Cost: each run takes under a minute, which stays inside GitHub's free Actions minutes, and uses a
  few hundred of YouTube's 10,000 free daily quota units.
- Keep the repo private: `data/` holds your numbers.
