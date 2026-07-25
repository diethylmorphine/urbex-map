"""Local dev: python run_local.py
Removes the webhook (if any), then runs uvicorn on :8080 + long polling.
Open http://localhost:8080 with DEV_MODE=1 in .env to test the UI in a browser."""
import asyncio
import logging

import uvicorn
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)

from api.index import app, bot, dp  # noqa: E402


async def main():
    await bot.delete_webhook(drop_pending_updates=False)
    server = uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=8080, log_level="info"))
    logging.info("Local: http://localhost:8080  (bot in polling mode)")
    await asyncio.gather(server.serve(), dp.start_polling(bot))


if __name__ == "__main__":
    asyncio.run(main())
