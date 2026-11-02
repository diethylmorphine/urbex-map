import hashlib
import hmac
import json
import os
import time
from urllib.parse import urlencode

os.environ.setdefault("BOT_TOKEN", "123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi")
os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SECRET_KEY", "test-placeholder")

import pytest
from fastapi.testclient import TestClient

import auth
from api.index import app


BOT_TOKEN = os.environ["BOT_TOKEN"]


def signed_init_data(auth_date: int, user: dict | None = None) -> str:
    values = {
        "auth_date": str(auth_date),
        "user": json.dumps(user or {"id": 123, "first_name": "Test"}, separators=(",", ":")),
    }
    check_string = "\n".join(f"{key}={value}" for key, value in sorted(values.items()))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    values["hash"] = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


def test_init_data_accepts_valid_recent_signature():
    now = int(time.time())
    assert auth.validate_init_data(signed_init_data(now - 60), BOT_TOKEN, now=now) == {
        "id": 123,
        "first_name": "Test",
    }


@pytest.mark.parametrize("age", [86_401, -31])
def test_init_data_rejects_stale_or_future_auth_date(age):
    now = 1_800_000_000
    assert auth.validate_init_data(
        signed_init_data(now - age), BOT_TOKEN, max_age_seconds=86_400, now=now,
    ) is None


def test_init_data_rejects_missing_auth_date_and_bad_signature():
    no_date = urlencode({"user": json.dumps({"id": 123}), "hash": "0" * 64})
    assert auth.validate_init_data(no_date, BOT_TOKEN) is None
    assert auth.validate_init_data(signed_init_data(int(time.time())).replace("hash=", "hash=0"), BOT_TOKEN) is None


def test_webhook_fails_closed_when_secret_missing_or_wrong(monkeypatch):
    client = TestClient(app)
    monkeypatch.setattr("api.index.WEBHOOK_SECRET", "")
    assert client.post("/api/webhook", json={}).status_code == 401

    monkeypatch.setattr("api.index.WEBHOOK_SECRET", "configured-secret")
    assert client.post(
        "/api/webhook", json={}, headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
    ).status_code == 401


def test_admin_delete_route_is_registered_once():
    routes = [
        route for route in app.routes
        if getattr(route, "path", None) == "/api/admin/delete"
        and "POST" in getattr(route, "methods", set())
    ]
    assert len(routes) == 1


def test_delete_location_implementation_is_defined_once():
    source = open(os.path.join(os.path.dirname(__file__), "..", "db.py"), encoding="utf-8").read()
    assert source.count("async def delete_location(") == 1
