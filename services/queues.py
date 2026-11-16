import re
from dataclasses import dataclass


@dataclass(frozen=True)
class QueueDef:
    key: str          # canonical "floor-kitchen", e.g. "2-1"
    floor: int
    kitchen: int
    rooms: tuple      # original order, duplicates preserved


def _parse_key(k):
    if isinstance(k, (tuple, list)) and len(k) == 2:
        try:
            return int(k[0]), int(k[1])
        except (TypeError, ValueError):
            return None
    nums = re.findall(r"\d+", str(k))
    return (int(nums[0]), int(nums[1])) if len(nums) == 2 else None


def build_queues(raw: dict) -> list:
    if not isinstance(raw, dict) or len(raw) != 8:
        raise ValueError(f"ROOM_QUEUES must contain exactly 8 queues, got {len(raw) if raw else 0}")
    parsed = [_parse_key(k) for k in raw]
    valid = (
        all(p is not None for p in parsed)
        and len(set(parsed)) == 8
        and all(1 <= f <= 4 and 1 <= c <= 2 for f, c in parsed)
    )
    coords = parsed if valid else [(i // 2 + 1, i % 2 + 1) for i in range(8)]
    out = []
    for (name, rooms), (f, c) in zip(raw.items(), coords):
        rooms_t = tuple(str(r).strip() for r in rooms)
        if not rooms_t or any(not r for r in rooms_t):
            raise ValueError(f"Queue {name!r} is empty or contains blank rooms")
        out.append(QueueDef(f"{f}-{c}", f, c, rooms_t))
    out.sort(key=lambda q: (q.floor, q.kitchen))
    return out


def load_queues() -> list:
    from data.room_queues import ROOM_QUEUES
    return build_queues(ROOM_QUEUES)
