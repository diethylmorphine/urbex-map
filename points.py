"""Points engine. All reward values live in points_config.json — edit that file,
restart nothing: config is re-read on every award, so changes apply instantly."""
import json
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "points_config.json"


def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def reward_for(action: str) -> int:
    return int(load_config()["rewards"].get(action, 0))


def tiers() -> list[dict]:
    return sorted(load_config()["tiers"], key=lambda t: t["tier"])


def max_visible_tier(points: int, is_admin: bool = False) -> int:
    """Highest tier a user can see. Admins see everything."""
    ts = tiers()
    if is_admin:
        return ts[-1]["tier"]
    visible = 0
    for t in ts:
        if points >= t["min_points"]:
            visible = t["tier"]
    return visible


async def award(tg_id: int, action: str) -> int:
    """Add points for an action, return the amount awarded."""
    import db
    amount = reward_for(action)
    if amount:
        await db.add_points(tg_id, amount)
    return amount
