"""Validates Telegram Mini App initData (HMAC-SHA256, per official docs).
Never trust the user object from the client without this check."""
import hashlib
import hmac
import json
from urllib.parse import parse_qsl


def validate_init_data(init_data: str, bot_token: str) -> dict | None:
    """Returns the Telegram user dict if the signature is valid, else None."""
    try:
        data = dict(parse_qsl(init_data, keep_blank_values=True))
        received_hash = data.pop("hash", "")
        if not received_hash:
            return None
        check_string = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
        secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        calculated = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calculated, received_hash):
            return None
        user = json.loads(data.get("user", "null"))
        return user if user and "id" in user else None
    except Exception:
        return None
