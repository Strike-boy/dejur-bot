import asyncio
import dataclasses
import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime

from aiogram.exceptions import (
    TelegramAPIError, TelegramMigrateToChat, TelegramNetworkError, TelegramRetryAfter,
)

from services.formatter import format_message
from services.rotation import Assignment, next_position, select

log = logging.getLogger(__name__)


@dataclass
class PublishResult:
    status: str            # sent | already | paused | no_group | failed
    message_id: int | None = None
    error: str | None = None


class DutyService:
    def __init__(self, db, queues, bot, config):
        self.db, self.queues, self.bot, self.config = db, queues, bot, config
        self._lens = {q.key: len(q.rooms) for q in queues}
        self.lock = asyncio.Lock()
        db.init_queues([q.key for q in queues])

    @staticmethod
    async def _run(fn, *a):
        return await asyncio.to_thread(fn, *a)

    def today(self) -> date:
        return datetime.now(self.config.tz).date()

    # ---- settings
    async def get_group_id(self):
        v = await self._run(self.db.get_setting, "group_id")
        if v:
            return int(v)
        return self.config.group_id

    async def set_group(self, chat_id: int):
        await self._run(self.db.set_setting, "group_id", chat_id)

    async def is_paused(self) -> bool:
        return (await self._run(self.db.get_setting, "paused", "0")) == "1"

    async def set_paused(self, paused: bool):
        await self._run(self.db.set_setting, "paused", "1" if paused else "0")

    # ---- read-only views (never advance queues)
    async def current_assignments(self, offset: int = 0):
        positions = await self._run(self.db.get_positions)
        return select(self.queues, positions, offset)

    async def preview_text(self) -> str:
        return format_message(await self.current_assignments())

    async def today_text(self) -> str:
        row = await self._run(self.db.get_publication, self.today().isoformat())
        if row and row["status"] == "sent":
            items = [Assignment(**d) for d in json.loads(row["assignments"])]
            return format_message(items)
        return "Bugungi e'lon hali yuborilmagan (har kuni 20:00 da).\n\n" + await self.preview_text()

    async def next_text(self) -> str:
        row = await self._run(self.db.get_publication, self.today().isoformat())
        sent_today = bool(row and row["status"] == "sent")
        items = await self.current_assignments(0 if sent_today else 1)
        return format_message(items, title="Ertangi oshxona navbatchilari:")

    async def status_text(self) -> str:
        positions = await self._run(self.db.get_positions)
        items = select(self.queues, positions)
        lines = []
        for q, a in zip(self.queues, items):
            lines.append(f"{q.floor}-qavat / {q.kitchen}-oshxona: {a.index + 1}/{len(q.rooms)} -> {a.room}")
        last = await self._run(self.db.last_sent)
        group = await self.get_group_id()
        return (
            f"Group: {group}\nPaused: {await self.is_paused()}\n"
            f"Last sent: {last['duty_date'] + ' (msg ' + str(last['message_id']) + ')' if last else 'never'}\n\n"
            "Next rooms:\n" + "\n".join(lines)
        )

    async def reset_queues(self):
        async with self.lock:
            await self._run(self.db.reset_positions)
        log.warning("All queues reset to position 0")

    # ---- publishing
    async def _send(self, chat_id: int, text: str):
        for attempt in range(1, 4):
            try:
                msg = await self.bot.send_message(chat_id, text)
                return chat_id, msg.message_id
            except TelegramRetryAfter as e:
                log.warning("Rate limited, sleeping %ss", e.retry_after)
                await asyncio.sleep(e.retry_after + 1)
            except TelegramMigrateToChat as e:
                chat_id = e.migrate_to_chat_id
                await self.set_group(chat_id)
                log.warning("Group migrated to supergroup %s", chat_id)
            except TelegramNetworkError as e:
                if attempt == 3:
                    raise
                log.warning("Network error (attempt %s): %s", attempt, e)
                await asyncio.sleep(5 * attempt)
        raise RuntimeError("Telegram send retries exhausted")

    async def publish(self, duty_date: date, source: str) -> PublishResult:
        async with self.lock:
            iso = duty_date.isoformat()
            if source in ("scheduler", "catchup") and await self.is_paused():
                log.info("Publishing paused, skipping %s", iso)
                return PublishResult("paused")
            chat_id = await self.get_group_id()
            if chat_id is None:
                log.error("Group not configured (use /setgroup)")
                return PublishResult("no_group", error="Group is not set")

            assignments = await self.current_assignments()
            state, msg_id = await self._run(
                self.db.claim, iso, [dataclasses.asdict(a) for a in assignments]
            )
            if state == "already":
                log.info("Duty date %s already published (msg %s)", iso, msg_id)
                return PublishResult("already", message_id=msg_id)

            try:
                chat_id, msg_id = await self._send(chat_id, format_message(assignments))
            except (TelegramAPIError, Exception) as e:  # noqa: BLE001
                await self._run(self.db.mark_failed, iso, repr(e))
                log.error("Publication %s failed (%s): %r", iso, source, e)
                return PublishResult("failed", error=str(e))

            new_pos = {a.key: next_position(a.index, self._lens[a.key]) for a in assignments}
            for attempt in range(1, 6):
                try:
                    await self._run(self.db.mark_sent, iso, chat_id, msg_id, new_pos)
                    break
                except sqlite3.Error as e:
                    log.error("DB commit failed after send (attempt %s): %s", attempt, e)
                    await asyncio.sleep(attempt)
            else:
                log.critical("Message %s sent for %s but state NOT saved!", msg_id, iso)
            log.info("Published %s (%s): chat=%s message_id=%s", iso, source, chat_id, msg_id)
            return PublishResult("sent", message_id=msg_id)

    async def notify_admins(self, text: str):
        for uid in self.config.admin_ids:
            try:
                await self.bot.send_message(uid, text)
            except Exception as e:  # noqa: BLE001
                log.warning("Could not notify admin %s: %s", uid, e)
