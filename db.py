"""Supabase REST layer (PostgREST) — same connection style as Pinky Promise:
SUPABASE_URL + SUPABASE_SECRET_KEY, no direct Postgres connection, no pooler.
Run schema.sql ONCE in the Supabase SQL Editor before first use.

All functions keep the exact signatures of the old asyncpg layer, and rows are
normalized to plain dicts with the same keys — bot.py / api/index.py unchanged."""
import os
from datetime import datetime, timezone

import httpx
from dotenv import load_dotenv

load_dotenv()

_client: httpx.AsyncClient | None = None


def _base() -> str:
    return os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1"


def _headers() -> dict:
    key = os.environ.get("SUPABASE_SECRET_KEY") or os.environ.get("SUPABASE_SERVICE_KEY", "")
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


async def _cli() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(base_url=_base(), headers=_headers(), timeout=15)
    return _client


async def _get(path: str, params: dict) -> list:
    c = await _cli()
    r = await c.get(path, params=params)
    r.raise_for_status()
    return r.json()


async def _post(path: str, json, prefer: str = "return=representation") -> list | None:
    c = await _cli()
    r = await c.post(path, json=json, headers={"Prefer": prefer})
    r.raise_for_status()
    return r.json() if r.text else None


async def _patch(path: str, params: dict, json: dict):
    c = await _cli()
    r = await c.patch(path, params=params, json=json)
    r.raise_for_status()


async def _delete(path: str, params: dict):
    c = await _cli()
    r = await c.delete(path, params=params)
    r.raise_for_status()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------- users ----------

async def upsert_user(tg_id: int, username: str | None, first_name: str | None):
    # merge-duplicates only touches the provided columns → points/is_admin stay intact
    await _post(
        "/users?on_conflict=tg_id",
        {"tg_id": tg_id, "username": username, "first_name": first_name},
        prefer="resolution=merge-duplicates,return=minimal",
    )


async def get_user(tg_id: int):
    rows = await _get("/users", {"tg_id": f"eq.{tg_id}", "select": "*"})
    return rows[0] if rows else None


async def set_admin(tg_id: int, flag: bool = True):
    await _patch("/users", {"tg_id": f"eq.{tg_id}"}, {"is_admin": flag})


async def admin_ids() -> list[int]:
    rows = await _get("/users", {"is_admin": "eq.true", "select": "tg_id"})
    return [r["tg_id"] for r in rows]


async def add_points(tg_id: int, amount: int):
    # atomic increment via RPC (defined in schema.sql)
    await _post("/rpc/add_points", {"uid": tg_id, "amount": amount}, prefer="return=minimal")


# ---------- locations ----------

async def create_location(author_id: int, title: str, description: str,
                          lat: float, lng: float, category: str) -> int:
    rows = await _post("/locations", {
        "title": title, "description": description, "lat": lat, "lng": lng,
        "category": category, "author_id": author_id,
    })
    return rows[0]["id"]


async def get_location(loc_id: int):
    rows = await _get("/locations", {"id": f"eq.{loc_id}", "select": "*"})
    return rows[0] if rows else None


async def verify_location(loc_id: int, admin_id: int, tier: int):
    await _patch("/locations", {"id": f"eq.{loc_id}"}, {
        "status": "approved", "tier": tier,
        "verified_by": admin_id, "verified_at": _now(),
    })


async def delete_location(loc_id: int):
    # likes/reviews/review_likes go with it via ON DELETE CASCADE (schema.sql)
    await _delete("/locations", {"id": f"eq.{loc_id}"})


async def reject_location(loc_id: int, admin_id: int):
    await _patch("/locations", {"id": f"eq.{loc_id}"}, {
        "status": "rejected", "verified_by": admin_id, "verified_at": _now(),
    })


async def delete_location(loc_id: int):
    """Hard-delete a location. review_likes/location_likes/reviews rows are
    removed by ON DELETE CASCADE (see schema.sql)."""
    await _delete("/locations", {"id": f"eq.{loc_id}"})


def _norm_location(r: dict) -> dict:
    """Flatten embedded relations to the keys the API expects."""
    r = dict(r)
    r["author_username"] = (r.pop("users", None) or {}).get("username")
    likes = r.pop("location_likes", [])
    reviews = r.pop("reviews", [])
    r["likes"] = likes[0]["count"] if likes else 0
    r["review_count"] = reviews[0]["count"] if reviews else 0
    return r


_LOC_SELECT = "*,users!locations_author_id_fkey(username),location_likes(count),reviews(count)"


async def visible_locations(max_tier: int, include_pending: bool):
    if include_pending:
        filt = {"or": f"(and(status.eq.approved,tier.lte.{max_tier}),status.eq.pending)"}
    else:
        filt = {"status": "eq.approved", "tier": f"lte.{max_tier}"}
    rows = await _get("/locations", {"select": _LOC_SELECT, **filt})
    return [_norm_location(r) for r in rows]


async def count_hidden(visible_tier: int) -> int:
    rows = await _get("/locations", {
        "status": "eq.approved", "tier": f"gt.{visible_tier}", "select": "id",
    })
    return len(rows)


async def toggle_location_like(user_id: int, loc_id: int) -> bool:
    """True if like added, False if removed."""
    params = {"user_id": f"eq.{user_id}", "location_id": f"eq.{loc_id}"}
    existing = await _get("/location_likes", {**params, "select": "user_id"})
    if existing:
        await _delete("/location_likes", params)
        return False
    await _post("/location_likes", {"user_id": user_id, "location_id": loc_id},
                prefer="return=minimal")
    return True


# ---------- reviews ----------

async def add_review(loc_id: int, author_id: int, text: str) -> int:
    rows = await _post("/reviews", {"location_id": loc_id, "author_id": author_id, "text": text})
    return rows[0]["id"]


async def get_reviews(loc_id: int):
    rows = await _get("/reviews", {
        "location_id": f"eq.{loc_id}",
        "select": "*,users!reviews_author_id_fkey(username,first_name),review_likes(count)",
        "order": "created_at.desc",
    })
    out = []
    for r in rows:
        r = dict(r)
        u = r.pop("users", None) or {}
        r["username"], r["first_name"] = u.get("username"), u.get("first_name")
        rl = r.pop("review_likes", [])
        r["likes"] = rl[0]["count"] if rl else 0
        out.append(r)
    return out


async def get_review(review_id: int):
    rows = await _get("/reviews", {"id": f"eq.{review_id}", "select": "*"})
    return rows[0] if rows else None


async def toggle_review_like(user_id: int, review_id: int) -> bool:
    params = {"user_id": f"eq.{user_id}", "review_id": f"eq.{review_id}"}
    existing = await _get("/review_likes", {**params, "select": "user_id"})
    if existing:
        await _delete("/review_likes", params)
        return False
    await _post("/review_likes", {"user_id": user_id, "review_id": review_id},
                prefer="return=minimal")
    return True
