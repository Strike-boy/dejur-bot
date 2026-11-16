def format_message(assignments, title="Bugungi oshxona navbatchilari:") -> str:
    by_floor = {}
    for a in sorted(assignments, key=lambda a: (a.floor, a.kitchen)):
        by_floor.setdefault(a.floor, []).append(a.room)
    blocks = [title]
    for floor, rooms in by_floor.items():
        blocks.append(f"{floor}-qavat:\n" + "\n".join(rooms))
    blocks.append("Navbatchilikni vaqtida bajarib topshiring.")
    return "\n\n".join(blocks)
