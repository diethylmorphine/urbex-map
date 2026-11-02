"""Validates Telegram Mini App initData (HMAC-SHA256, per official docs).
Never trust the user object from the client without this check."""
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl


def validate_init_data(
    init_data: str,
    bot_token: str,
    max_age_seconds: int = 86_400,
    now: int | None = None,
) -> dict | None:
    """Return the Telegram user dict only for valid, fresh signed initData."""
    try:
        data = dict(parse_qsl(init_data, keep_blank_values=True))
        received_hash = data.pop("hash", "")
        auth_date_raw = data.get("auth_date", "")
        if not received_hash or not auth_date_raw.isdecimal() or max_age_seconds <= 0:
            return None
        check_string = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
        secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        calculated = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calculated, received_hash):
            return None
        auth_date = int(auth_date_raw)
        current_time = int(time.time()) if now is None else now
        if auth_date > current_time + 30 or current_time - auth_date > max_age_seconds:
            return None
        user = json.loads(data.get("user", "null"))
        return user if user and "id" in user else None
    except Exception:
        return None
