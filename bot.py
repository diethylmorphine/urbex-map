"""aiogram 3 bot: /start with Mini App button, admin moderation flow.
New pending locations are pushed to every admin with inline verify buttons."""
import os

from dotenv import load_dotenv

load_dotenv()

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)

import db
import points

router = Router()

WEBAPP_URL = os.environ.get("WEBAPP_URL", "https://morphine.app")
OWNER_ID = int(os.environ.get("OWNER_ID", "0"))


def webapp_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🗺 OPEN MAP", web_app=WebAppInfo(url=WEBAPP_URL))
    ]])


def moderation_kb(loc_id: int) -> InlineKeyboardMarkup:
    tier_row = [
        InlineKeyboardButton(text=f"✅ T{t['tier']} {t['name']}",
                             callback_data=f"ap:{loc_id}:{t['tier']}")
        for t in points.tiers()
    ]
    # two tiers per row so it doesn't overflow
    rows = [tier_row[i:i + 2] for i in range(0, len(tier_row), 2)]
    rows.append([InlineKeyboardButton(text="❌ REJECT", callback_data=f"rj:{loc_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def notify_admins(bot: Bot, loc_id: int):
    """Called by the API server when a new location is submitted."""
    loc = await db.get_location(loc_id)
    if not loc:
        return
    author = await db.get_user(loc["author_id"])
    uname = f"@{author['username']}" if author and author["username"] else loc["author_id"]
    text = (
        f"🛰 <b>NEW SPOT PENDING</b> #{loc['id']}\n\n"
        f"<b>{loc['title']}</b>\n"
        f"{loc['description'] or '—'}\n\n"
        f"📍 <code>{loc['lat']:.6f}, {loc['lng']:.6f}</code>\n"
        f"🏷 {loc['category']}\n"
        f"👤 {uname}\n\n"
        f"Pick a tier to approve:"
    )
    for admin_id in await db.admin_ids():
        try:
            await bot.send_message(admin_id, text, reply_markup=moderation_kb(loc_id))
        except Exception:
            pass  # admin blocked the bot etc.


@router.message(CommandStart())
async def cmd_start(m: Message):
    await db.upsert_user(m.from_user.id, m.from_user.username, m.from_user.first_name)
    # first user with OWNER_ID becomes admin automatically
    if OWNER_ID and m.from_user.id == OWNER_ID:
        await db.set_admin(m.from_user.id, True)
    u = await db.get_user(m.from_user.id)
    tier = points.max_visible_tier(u["points"], bool(u["is_admin"]))
    await m.answer(
        f"⚠️ <b>URBEX GRID</b>\n\n"
        f"Points: <b>{u['points']}</b> · Access tier: <b>T{tier}</b>\n\n"
        f"Drop spots, get them verified, earn points, unlock deeper layers of the map.",
        reply_markup=webapp_kb(),
    )


@router.message(Command("points"))
async def cmd_points(m: Message):
    u = await db.get_user(m.from_user.id)
    if not u:
        await m.answer("Hit /start first.")
        return
    cfg = points.load_config()
    tier = points.max_visible_tier(u["points"], bool(u["is_admin"]))
    lines = [f"💠 Points: <b>{u['points']}</b> · Tier: <b>T{tier}</b>", "", "<b>Earn:</b>"]
    labels = {
        "location_verified": "Spot approved by admin",
        "location_liked": "Someone liked your spot",
        "review_posted": "You posted a review",
        "review_liked": "Someone liked your review",
    }
    for k, v in cfg["rewards"].items():
        lines.append(f"  +{v} — {labels.get(k, k)}")
    lines.append("")
    lines.append("<b>Tiers:</b>")
    for t in cfg["tiers"]:
        lines.append(f"  T{t['tier']} {t['name']} — {t['min_points']} pts")
    await m.answer("\n".join(lines))


@router.message(Command("addadmin"))
async def cmd_addadmin(m: Message):
    """Owner only: /addadmin <tg_id>"""
    if m.from_user.id != OWNER_ID:
        return
    parts = (m.text or "").split()
    if len(parts) != 2 or not parts[1].lstrip("-").isdigit():
        await m.answer("Usage: /addadmin <tg_id>")
        return
    target = int(parts[1])
    if not await db.get_user(target):
        await m.answer("That user hasn't started the bot yet.")
        return
    await db.set_admin(target, True)
    await m.answer(f"✅ {target} is now an admin.")


@router.callback_query(F.data.startswith("ap:"))
async def cb_approve(cb: CallbackQuery):
    admin = await db.get_user(cb.from_user.id)
    if not admin or not admin["is_admin"]:
        await cb.answer("Admins only.", show_alert=True)
        return
    _, loc_id, tier = cb.data.split(":")
    loc_id, tier = int(loc_id), int(tier)
    loc = await db.get_location(loc_id)
    if not loc or loc["status"] != "pending":
        await cb.answer("Already handled.")
        return
    await db.verify_location(loc_id, cb.from_user.id, tier)
    amount = await points.award(loc["author_id"], "location_verified")
    tier_name = next((t["name"] for t in points.tiers() if t["tier"] == tier), str(tier))
    await cb.message.edit_text(
        cb.message.html_text + f"\n\n✅ <b>APPROVED → T{tier} {tier_name}</b> by @{cb.from_user.username}"
    )
    try:
        await cb.bot.send_message(
            loc["author_id"],
            f"✅ Your spot <b>{loc['title']}</b> was verified (T{tier} {tier_name}). +{amount} pts",
        )
    except Exception:
        pass
    await cb.answer(f"Approved as T{tier}")


@router.callback_query(F.data.startswith("rj:"))
async def cb_reject(cb: CallbackQuery):
    admin = await db.get_user(cb.from_user.id)
    if not admin or not admin["is_admin"]:
        await cb.answer("Admins only.", show_alert=True)
        return
    loc_id = int(cb.data.split(":")[1])
    loc = await db.get_location(loc_id)
    if not loc or loc["status"] != "pending":
        await cb.answer("Already handled.")
        return
    await db.reject_location(loc_id, cb.from_user.id)
    await cb.message.edit_text(cb.message.html_text + "\n\n❌ <b>REJECTED</b>")
    try:
        await cb.bot.send_message(loc["author_id"], f"❌ Your spot <b>{loc['title']}</b> was rejected.")
    except Exception:
        pass
    await cb.answer("Rejected")


@router.callback_query(F.data.startswith("del:"))
async def cb_delete(cb: CallbackQuery):
    admin = await db.get_user(cb.from_user.id)
    if not admin or not admin["is_admin"]:
        await cb.answer("Admins only.", show_alert=True)
        return
    loc_id = int(cb.data.split(":")[1])
    loc = await db.get_location(loc_id)
    if not loc:
        await cb.answer("Already gone.")
        return
    await db.delete_location(loc_id)
    await cb.message.edit_text(cb.message.html_text + "\n\n🗑 <b>DELETED</b>")
    try:
        await cb.bot.send_message(loc["author_id"], f"🗑 Your spot <b>{loc['title']}</b> was removed by an admin.")
    except Exception:
        pass
    await cb.answer("Deleted")
