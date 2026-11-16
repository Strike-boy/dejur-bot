import asyncio
import logging
import os
from datetime import datetime
from logging.handlers import RotatingFileHandler

from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config import load_config
from database.db import Database
from handlers.admin import build_admin_router
from handlers.public import router as public_router
from services.duty_service import DutyService
from services.queues import load_queues

log = logging.getLogger("bot")


def setup_logging():
    os.makedirs("logs", exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    file_h = RotatingFileHandler("logs/bot.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    file_h.setFormatter(fmt)
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    logging.basicConfig(level=logging.INFO, handlers=[file_h, console])


async def run_daily(service: DutyService):
    duty_date = service.today()
    res = None
    for attempt in range(1, 4):
        res = await service.publish(duty_date, source="scheduler")
        if res.status != "failed":
            break
        log.warning("Daily publish failed (attempt %s/3): %s", attempt, res.error)
        if attempt < 3:
            await asyncio.sleep(300)
    if res.status in ("failed", "no_group"):
        await service.notify_admins(
            f"Kunlik e'lon yuborilmadi ({duty_date}): {res.error}\nNavbatlar siljimadi. /send bilan qayta urinib ko'ring."
        )


async def main():
    setup_logging()
    config = load_config()
    queues = load_queues()          # fails loudly if ROOM_QUEUES is invalid
    db = Database(config.db_path)

    bot = Bot(config.bot_token)
    service = DutyService(db, queues, bot, config)

    dp = Dispatcher()
    dp["service"] = service
    dp.include_router(build_admin_router(config.admin_ids))
    dp.include_router(public_router)

    scheduler = AsyncIOScheduler(timezone=config.tz)
    scheduler.add_job(
        run_daily,
        CronTrigger(hour=config.send_hour, minute=config.send_minute, timezone=config.tz),
        args=[service],
        id="daily_duty",
        coalesce=True,
        max_instances=1,
        misfire_grace_time=3600,
        replace_existing=True,
    )
    scheduler.start()
    log.info("Scheduler started: daily at %02d:%02d Asia/Tashkent", config.send_hour, config.send_minute)

    await bot.set_my_commands([
        BotCommand(command="today", description="Bugungi navbatchilar"),
        BotCommand(command="next", description="Ertangi navbatchilar"),
        BotCommand(command="help", description="Yordam"),
    ])
    await bot.delete_webhook(drop_pending_updates=False)

    # Catch-up: if the process was down at 20:00 and today's post is missing
    if config.catchup_on_start:
        now = datetime.now(config.tz)
        if (now.hour, now.minute) >= (config.send_hour, config.send_minute):
            asyncio.create_task(run_daily(service))

    try:
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)
        await bot.session.close()
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
