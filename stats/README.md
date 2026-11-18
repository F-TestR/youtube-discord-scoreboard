# PIRACY social stats, V2

Every hour this bot reads how PIRACY's videos are doing on YouTube Shorts, TikTok and
Instagram Reels (plus the Discord member count), keeps the full history, and then:

- **updates one pinned scoreboard in Discord**, with a chart, the top videos, a short
  "ship's log" of what changed, and buttons into the website;
- **posts alerts** only when something happens: a new video, a 24-hour and 7-day check-in,
  a video taking off (2× your usual), a milestone, an app that stops answering (and when
  it's back), and the Monday report at 18:00 UK;
- **rebuilds the website** (GitHub Pages): overview, every video with its growth curve,
  analytics, research on what's working for other Roblox devs, the trend bot's board,
  and a Status page that shows what's connected and how to connect the rest.

Nothing needs typing in once an app is connected. Apps are never added together, because
each counts views differently, and a missing number stays blank rather than becoming zero.

## What's automatic today, and what needs a one-off sign-in

| App | Without a sign-in | After connecting it once |
|---|---|---|
| YouTube Shorts | Views, likes, comments, subscribers, new Shorts (API key, already set) | **YouTube Analytics** adds watch time, % viewed, subscribers gained and shares per Short |
| TikTok | The typed-in sheet (`manual/posts.csv`) | Views, likes, comments, shares, followers, new TikToks, all automatic |
| Instagram Reels | Nothing | Views, reach, likes, comments, shares, saves, watch time, followers |
| Discord | Member count (invite link) | — |

The website's **Status** page has the steps for each, with a **Connect** button. In short:
make a free developer app for the platform, add its two keys as GitHub secrets, press
Connect, and paste the one-time code into the **Connect an app** workflow. The bot keeps the
sign-in alive by itself after that (stored encrypted in `data/vault.json`).

## Files

| Path | What it is |
|---|---|
| `run.py` | The hourly run |
| `piracy/collect.py` | Reading YouTube, YouTube Analytics, TikTok, Instagram, Discord, the typed-in sheet |
| `piracy/store.py` | The memory: `data/posts.json` and the history files in `data/history/` |
| `piracy/analysis.py` | Gains, growth curves, "your usual", milestones, the ship's log |
| `piracy/research.py` | The daily scan of other Roblox dev Shorts, the trend bot's board, the field guide |
| `piracy/discord_v2.py` | Every Discord message |
| `piracy/charts.py` | The chart images Discord shows |
| `site/` | The website (plain HTML, CSS and JavaScript, reading `data.json`) |
| `config.json` | Settings: YouTube handle, Discord invite, alert levels, scan searches |
| `manual/posts.csv` | Typed-in numbers, only for apps that aren't connected |
| `manual/links.csv` | Fix a wrong match between copies of the same clip on different apps |
| `connect.py` | Used by the Connect an app workflow |
| `tests/` | Offline tests, including an eight-day rehearsal with a pretend internet |

## Settings you might change (`config.json`)

- `discord.live`: `true` posts to Discord; `false` is shadow mode (messages go to `data/outbox.json`).
- `site.ready`: `true` adds the website buttons to Discord messages.
- `alerts.take_off_multiplier` / `take_off_min_views`: when a "taking off" alert fires.
- `scanner.queries`: the YouTube searches used to find other devs' Shorts.

## Running it by hand

Actions tab → **PIRACY stats V2** → Run workflow. Tick **Practice run** to send nothing to
Discord, or **Post the weekly report now** to post it straight away.

## The first bot (V1)

V1 lives in `piracy-bot/` and is kept as it was. Its workflow still exists but no longer
runs on a schedule, so it can be switched back on (add the `schedule:` lines back to
`.github/workflows/piracy-stats-bot.yml`) if V2 ever needs to be rolled back. V2 started
with V1's full history, so the charts begin on 15 Nov 2026.

## Costs

Free. The repo is public, so GitHub Actions minutes are free, and GitHub Pages is free.
YouTube use is about 100 units a day for our own channel plus about 600 for the daily scan,
well inside the free 10,000.
