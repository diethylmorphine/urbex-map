# URBEX GRID — Telegram Mini App for urban exploring

Dark interactive map: explorers drop spots → admins verify + assign a tier →
users unlock deeper tiers by earning points. Rewards live in `points_config.json`.

**Stack:** aiogram 3 (webhook on prod / polling locally) · FastAPI · Supabase
via REST API (httpx) · Vercel · Leaflet + CARTO dark tiles.

## Screenshot

<!-- TODO: add a screenshot or GIF of the map with sample data. -->

## Data & Privacy

The app stores exact location coordinates, Telegram user IDs, usernames, and first names in Supabase to support submitted spots, account points, and moderation. Spot titles, descriptions, and reviews are also visible according to the map's approval and tier rules. Do not submit private or sensitive locations. The project currently has no self-service data deletion flow; an operator must delete the user's records from Supabase, including related locations, reviews, and likes according to the foreign-key relationships in `schema.sql`.

```
urbex-map/
├── api/index.py        # FastAPI — Vercel serverless function (/api/*, webhook)
├── public/             # Mini App (served by Vercel CDN at morphine.app)
├── bot.py              # aiogram handlers + admin DM moderation
├── db.py               # Supabase REST (PostgREST) via httpx
├── schema.sql          # run ONCE in Supabase SQL Editor
├── points.py           # JSON-driven rewards & tiers
├── auth.py             # Telegram initData HMAC validation
├── run_local.py        # localhost: uvicorn + long polling
├── set_webhook.py      # one-shot prod webhook setup
├── vercel.json
└── .env.example
```

## 1. Supabase (same connection style as Pinky Promise)

1. supabase.com → New project (or reuse the Pinky Promise project — tables
   won't clash).
2. **SQL Editor** → paste `schema.sql` → Run (one time). Creates tables,
   the `add_points` RPC, and locks tables with RLS.
3. Project Settings → Data API: copy **Project URL** → `SUPABASE_URL` and the
   **service_role / secret key** → `SUPABASE_SECRET_KEY`.

No `DATABASE_URL`, no poolers, no DB password — the backend talks to Supabase
over its REST API (PostgREST), same as Pinky Promise. The secret key bypasses
RLS, so it must live only in env vars, never in `public/`.

## 2. Local testing (localhost, no tunnel)

```bash
cp .env.example .env        # fill BOT_TOKEN, SUPABASE_URL, SUPABASE_SECRET_KEY, OWNER_ID
# in .env uncomment:  WEBAPP_URL=http://localhost:8080, DEV_MODE=1
pip install -r requirements.txt
python run_local.py
```

- Bot runs in **polling** (webhook is auto-removed on start) → moderation DMs work.
- Open **http://localhost:8080** in a normal browser: `DEV_MODE=1` gives you a
  fake local admin, so you can click through the whole UI without Telegram.
- To test the real Mini App inside Telegram you still need HTTPS
  (`ngrok http 8080` → temporarily set that URL in @BotFather / WEBAPP_URL).

Telegram `initData` is rejected after `INIT_DATA_MAX_AGE_SECONDS` (defaults to 86400 seconds / 24 hours). Production webhook requests are rejected if `WEBHOOK_SECRET` is unset or does not match Telegram's secret-token header.

⚠️ `DEV_MODE` disables auth. Local only. Never add it to Vercel env vars.

## 3. Deploy to Vercel + morphine.app

```bash
npm i -g vercel
vercel                      # link the project
vercel env add BOT_TOKEN
vercel env add SUPABASE_URL
vercel env add SUPABASE_SECRET_KEY
vercel env add OWNER_ID
vercel env add WEBAPP_URL   # https://morphine.app
vercel env add WEBHOOK_SECRET
vercel --prod
```

Then:
1. Vercel dashboard → Project → **Domains** → add `morphine.app`
   (Vercel shows the exact DNS records to set at your registrar).
2. Point Telegram at the webhook (run locally with prod `.env` values):
   ```bash
   python set_webhook.py     # → https://morphine.app/api/webhook
   ```
3. @BotFather → your bot → Mini App / menu button URL → `https://morphine.app`.
4. `/start` as OWNER_ID → you're admin. `/addadmin <tg_id>` for the crew.

**Switching back to local dev is zero-config**: `run_local.py` deletes the
webhook and polls; re-run `set_webhook.py` when you're done.

## Points & tiers — points_config.json

```json
"rewards": {
  "location_verified": 25,   "location_liked": 3,
  "review_posted": 2,        "review_liked": 1
},
"tiers": [
  { "tier": 0, "name": "STREET",     "min_points": 0   },
  { "tier": 1, "name": "ROOFTOP",    "min_points": 25  },
  { "tier": 2, "name": "RESTRICTED", "min_points": 75  },
  { "tier": 3, "name": "DEEP",       "min_points": 150 }
]
```
Re-read on every award. On Vercel, edits require a redeploy (file ships with
the bundle); locally they apply instantly. Self-likes/un-likes never award.

## How verification flows

```
pin dropped ──► pending ──► DM to every admin (inline: ✅T0–T3 / ❌)
                              + visible in webapp ADMIN MODE
                    approve ──► author +points ──► spot live for users
                                                   with clearance ≥ tier
```
Tier gating is enforced in SQL — locked spots never leave the server.

## Bot commands
| Command | Who | What |
|---|---|---|
| `/start` | all | register + OPEN MAP button |
| `/points` | all | balance + reward/tier table |
| `/addadmin <id>` | owner | promote admin |
