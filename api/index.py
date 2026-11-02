"""URBEX GRID — FastAPI app. Works in two modes:

  • Vercel (prod, morphine.app): serverless function at /api/*, bot via webhook,
    static files served by Vercel's CDN from /public.
  • Localhost: run_local.py starts uvicorn (this app also serves /public) and
    aiogram long polling — no webhook, no tunnel needed for API testing.

Auth: `Authorization: tma <initData>` verified server-side. DEV_MODE=1 bypasses
auth with a fake local user — NEVER set it on Vercel."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import Update
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import auth
import db
import points
from bot import notify_admins, router

BOT_TOKEN = os.environ["BOT_TOKEN"]
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")
DEV_MODE = os.environ.get("DEV_MODE") == "1"
DEV_USER_ID = int(os.environ.get("DEV_USER_ID", "1"))
INIT_DATA_MAX_AGE_SECONDS = int(os.environ.get("INIT_DATA_MAX_AGE_SECONDS", "86400"))

bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
dp.include_router(router)

app = FastAPI(docs_url=None, redoc_url=None)

PUBLIC_DIR = Path(__file__).resolve().parent.parent / "public"


# ---------- auth ----------

async def current_user(request: Request):
    header = request.headers.get("Authorization", "")
    if header.startswith("tma "):
        tg_user = auth.validate_init_data(
            header[4:], BOT_TOKEN, max_age_seconds=INIT_DATA_MAX_AGE_SECONDS,
        )
        if tg_user:
            await db.upsert_user(tg_user["id"], tg_user.get("username"), tg_user.get("first_name"))
            return await db.get_user(tg_user["id"])
    if DEV_MODE:  # local browser testing without Telegram
        await db.upsert_user(DEV_USER_ID, "dev", "Dev")
        await db.set_admin(DEV_USER_ID, True)
        return await db.get_user(DEV_USER_ID)
    raise HTTPException(401, "unauthorized")


def require_admin(u):
    if not u["is_admin"]:
        raise HTTPException(403, "admins only")


def me_payload(u) -> dict:
    tier = points.max_visible_tier(u["points"], bool(u["is_admin"]))
    return {
        "id": u["tg_id"], "username": u["username"], "first_name": u["first_name"],
        "points": u["points"], "is_admin": bool(u["is_admin"]), "visible_tier": tier,
    }


# ---------- telegram webhook (prod) ----------

@app.post("/api/webhook")
async def telegram_webhook(request: Request):
    if not WEBHOOK_SECRET or request.headers.get("X-Telegram-Bot-Api-Secret-Token") != WEBHOOK_SECRET:
        raise HTTPException(401)
    update = Update.model_validate(await request.json(), context={"bot": bot})
    await dp.feed_update(bot, update)
    return {"ok": True}


# ---------- api ----------

@app.get("/api/me")
async def api_me(u=Depends(current_user)):
    return {"me": me_payload(u), "tiers": points.tiers()}


@app.get("/api/locations")
async def api_locations(u=Depends(current_user)):
    tier = points.max_visible_tier(u["points"], bool(u["is_admin"]))
    rows = await db.visible_locations(tier, include_pending=bool(u["is_admin"]))
    hidden = await db.count_hidden(tier)
    return {
        "locations": [{
            "id": r["id"], "title": r["title"], "description": r["description"],
            "lat": r["lat"], "lng": r["lng"], "category": r["category"],
            "tier": r["tier"], "status": r["status"], "likes": r["likes"],
            "review_count": r["review_count"], "author": r["author_username"],
            "mine": r["author_id"] == u["tg_id"],
        } for r in rows],
        "hidden_count": hidden,
    }


@app.post("/api/locations")
async def api_create_location(request: Request, u=Depends(current_user)):
    body = await request.json()
    title = (body.get("title") or "").strip()[:80]
    desc = (body.get("description") or "").strip()[:600]
    cat = (body.get("category") or "other").strip()[:30]
    try:
        lat, lng = float(body["lat"]), float(body["lng"])
        assert -90 <= lat <= 90 and -180 <= lng <= 180
    except (KeyError, ValueError, AssertionError):
        raise HTTPException(400, "bad coordinates")
    if not title:
        raise HTTPException(400, "title required")
    loc_id = await db.create_location(u["tg_id"], title, desc, lat, lng, cat)
    try:
        await notify_admins(bot, loc_id)
    except Exception:
        pass  # never fail a submission because a DM failed
    return {"id": loc_id, "status": "pending"}


@app.post("/api/locations/{loc_id}/like")
async def api_like_location(loc_id: int, u=Depends(current_user)):
    loc = await db.get_location(loc_id)
    if not loc or loc["status"] != "approved":
        raise HTTPException(404)
    tier = points.max_visible_tier(u["points"], bool(u["is_admin"]))
    if loc["tier"] > tier:
        raise HTTPException(403, "locked")
    added = await db.toggle_location_like(u["tg_id"], loc_id)
    if added and loc["author_id"] != u["tg_id"]:
        await points.award(loc["author_id"], "location_liked")
    return {"liked": added}


@app.get("/api/locations/{loc_id}/reviews")
async def api_reviews(loc_id: int, u=Depends(current_user)):
    rows = await db.get_reviews(loc_id)
    return {"reviews": [{
        "id": r["id"], "text": r["text"], "likes": r["likes"],
        "author": r["username"] or r["first_name"] or "anon",
        "created_at": str(r["created_at"]),
    } for r in rows]}


@app.post("/api/locations/{loc_id}/reviews")
async def api_add_review(loc_id: int, request: Request, u=Depends(current_user)):
    loc = await db.get_location(loc_id)
    if not loc or loc["status"] != "approved":
        raise HTTPException(404)
    body = await request.json()
    text = (body.get("text") or "").strip()[:500]
    if not text:
        raise HTTPException(400, "empty")
    rid = await db.add_review(loc_id, u["tg_id"], text)
    await points.award(u["tg_id"], "review_posted")
    return {"id": rid}


@app.post("/api/reviews/{review_id}/like")
async def api_like_review(review_id: int, u=Depends(current_user)):
    review = await db.get_review(review_id)
    if not review:
        raise HTTPException(404)
    added = await db.toggle_review_like(u["tg_id"], review_id)
    if added and review["author_id"] != u["tg_id"]:
        await points.award(review["author_id"], "review_liked")
    return {"liked": added}


# ---------- admin ----------

@app.post("/api/admin/verify")
async def api_admin_verify(request: Request, u=Depends(current_user)):
    require_admin(u)
    body = await request.json()
    loc_id, tier = int(body["id"]), int(body["tier"])
    loc = await db.get_location(loc_id)
    if not loc or loc["status"] != "pending":
        raise HTTPException(400, "not pending")
    await db.verify_location(loc_id, u["tg_id"], tier)
    amount = await points.award(loc["author_id"], "location_verified")
    try:
        await bot.send_message(loc["author_id"],
                               f"✅ Your spot <b>{loc['title']}</b> was verified (T{tier}). +{amount} pts")
    except Exception:
        pass
    return {"ok": True}


@app.post("/api/admin/reject")
async def api_admin_reject(request: Request, u=Depends(current_user)):
    require_admin(u)
    body = await request.json()
    loc_id = int(body["id"])
    loc = await db.get_location(loc_id)
    if not loc or loc["status"] != "pending":
        raise HTTPException(400, "not pending")
    await db.reject_location(loc_id, u["tg_id"])
    try:
        await bot.send_message(loc["author_id"], f"❌ Spot <b>{loc['title']}</b> rejected.")
    except Exception:
        pass
    return {"ok": True}


@app.post("/api/admin/delete")
async def api_admin_delete(request: Request, u=Depends(current_user)):
    """Permanently remove a spot (any status) plus its likes and reviews."""
    require_admin(u)
    body = await request.json()
    loc_id = int(body["id"])
    loc = await db.get_location(loc_id)
    if not loc:
        raise HTTPException(404, "not found")
    await db.delete_location(loc_id)
    try:
        await bot.send_message(loc["author_id"], f"🗑 Your spot <b>{loc['title']}</b> was removed by an admin.")
    except Exception:
        pass
    return {"ok": True}


# ---------- static (localhost; on Vercel the CDN serves /public) ----------

if PUBLIC_DIR.exists():
    @app.get("/")
    async def index():
        return FileResponse(PUBLIC_DIR / "index.html")

    app.mount("/", StaticFiles(directory=PUBLIC_DIR), name="static")
