import os
import tempfile
import unittest
from datetime import date, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from config import Config
from database.db import Database
from services.duty_service import DutyService
from services.queues import build_queues
from services.rotation import next_position, select

RAW = {f"{f}-{k}": ["101", "102", "101"] for f in range(1, 5) for k in (1, 2)}
RAW["2-2"] = ["205", "206"]


class FakeBot:
    def __init__(self, fail=False):
        self.fail, self.sent, self._id = fail, [], 100

    async def send_message(self, chat_id, text):
        if self.fail:
            raise RuntimeError("boom")
        self._id += 1
        self.sent.append((chat_id, text))
        return SimpleNamespace(message_id=self._id)


def make(path, bot):
    cfg = Config("x", frozenset({1}), -100, path, ZoneInfo("Asia/Tashkent"), 20, 0, False)
    return DutyService(Database(path), build_queues(RAW), bot, cfg)


class Tests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "t.db")

    def test_rotation_wraps_and_keeps_duplicates(self):
        q = build_queues(RAW)
        seq, pos = [], 0
        for _ in range(7):
            a = select(q, {"1-1": pos})[0]
            seq.append(a.room)
            pos = next_position(a.index, 3)
        self.assertEqual(seq, ["101", "102", "101", "101", "102", "101", "101"])

    def test_queue_validation(self):
        with self.assertRaises(ValueError):
            build_queues({})
        with self.assertRaises(ValueError):
            build_queues({**RAW, "1-1": []})

    async def test_publish_advances_once_and_blocks_duplicates(self):
        bot = FakeBot()
        s = make(self.path, bot)
        d = date(2026, 1, 1)
        self.assertEqual((await s.publish(d, "manual")).status, "sent")
        self.assertEqual((await s.publish(d, "manual")).status, "already")
        self.assertEqual(len(bot.sent), 1)
        self.assertEqual(s.db.get_positions()["1-1"], 1)

    async def test_failure_does_not_advance_then_retry_works(self):
        bad = FakeBot(fail=True)
        s = make(self.path, bad)
        d = date(2026, 1, 1)
        self.assertEqual((await s.publish(d, "manual")).status, "failed")
        self.assertTrue(all(p == 0 for p in s.db.get_positions().values()))
        s.bot = FakeBot()
        self.assertEqual((await s.publish(d, "manual")).status, "sent")
        self.assertEqual(s.db.get_positions()["1-1"], 1)

    async def test_preview_does_not_advance(self):
        s = make(self.path, FakeBot())
        await s.preview_text()
        await s.next_text()
        self.assertTrue(all(p == 0 for p in s.db.get_positions().values()))

    async def test_progress_survives_restart_and_queues_independent(self):
        s = make(self.path, FakeBot())
        d = date(2026, 1, 1)
        for i in range(2):
            await s.publish(d + timedelta(days=i), "manual")
        s.db.close()
        s2 = make(self.path, FakeBot())
        pos = s2.db.get_positions()
        self.assertEqual(pos["1-1"], 2)   # 3 rooms
        self.assertEqual(pos["2-2"], 0)   # 2 rooms, wrapped back to start

    async def test_pause_blocks_scheduler_but_not_manual(self):
        bot = FakeBot()
        s = make(self.path, bot)
        await s.set_paused(True)
        d = date(2026, 1, 1)
        self.assertEqual((await s.publish(d, "scheduler")).status, "paused")
        self.assertEqual((await s.publish(d, "manual")).status, "sent")

    async def test_reset(self):
        s = make(self.path, FakeBot())
        await s.publish(date(2026, 1, 1), "manual")
        await s.reset_queues()
        self.assertTrue(all(p == 0 for p in s.db.get_positions().values()))


if __name__ == "__main__":
    unittest.main()
