"""One-shot: point Telegram at the production webhook.
Run AFTER deploying to Vercel:  python set_webhook.py"""
import asyncio
import os

from dotenv import load_dotenv

load_dotenv()

from aiogram import Bot  # noqa: E402


async def main():
    bot = Bot(os.environ["BOT_TOKEN"])
    url = os.environ.get("WEBAPP_URL", "https://morphine.app").rstrip("/") + "/api/webhook"
    await bot.set_webhook(
        url,
        secret_token=os.environ.get("WEBHOOK_SECRET") or None,
        allowed_updates=["message", "callback_query"],
        drop_pending_updates=True,
    )
    info = await bot.get_webhook_info()
    print(f"Webhook set: {info.url}")
    await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
