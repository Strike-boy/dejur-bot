from dataclasses import dataclass


@dataclass(frozen=True)
class Assignment:
    key: str
    floor: int
    kitchen: int
    index: int   # list index (not room number), so duplicates stay distinct
    room: str


def next_position(index: int, length: int) -> int:
    return (index + 1) % length


def select(queues, positions: dict, offset: int = 0) -> list:
    """One room per queue. Never mutates state."""
    result = []
    for q in queues:
        idx = (positions.get(q.key, 0) + offset) % len(q.rooms)
        result.append(Assignment(q.key, q.floor, q.kitchen, idx, q.rooms[idx]))
    return result
