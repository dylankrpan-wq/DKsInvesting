"""Per-ticker notes/journal."""
from __future__ import annotations
import sqlite3
from dk.config import DB_PATH


def add(symbol: str, body: str, tags: str = "", pinned: bool = False) -> int:
    body = (body or "").strip()
    if not body:
        return 0
    with sqlite3.connect(DB_PATH) as c:
        cur = c.execute(
            "INSERT INTO notes (symbol, body, tags, pinned) VALUES (?, ?, ?, ?)",
            (symbol.upper(), body, (tags or "").strip(), 1 if pinned else 0),
        )
        c.commit()
        return cur.lastrowid


def update(note_id: int, body: str | None = None, tags: str | None = None,
           pinned: bool | None = None) -> None:
    sets = []
    vals = []
    if body is not None:
        sets.append("body=?"); vals.append(body)
    if tags is not None:
        sets.append("tags=?"); vals.append(tags)
    if pinned is not None:
        sets.append("pinned=?"); vals.append(1 if pinned else 0)
    sets.append("updated_at=CURRENT_TIMESTAMP")
    if not sets:
        return
    vals.append(note_id)
    with sqlite3.connect(DB_PATH) as c:
        c.execute(f"UPDATE notes SET {', '.join(sets)} WHERE id=?", vals)
        c.commit()


def delete(note_id: int) -> None:
    with sqlite3.connect(DB_PATH) as c:
        c.execute("DELETE FROM notes WHERE id=?", (note_id,))
        c.commit()


def list_for(symbol: str) -> list[dict]:
    with sqlite3.connect(DB_PATH) as c:
        c.row_factory = sqlite3.Row
        rows = c.execute(
            """SELECT id, symbol, body, tags, pinned, created_at, updated_at
               FROM notes WHERE symbol=?
               ORDER BY pinned DESC, created_at DESC""",
            (symbol.upper(),),
        ).fetchall()
        return [dict(r) for r in rows]


def list_all_recent(limit: int = 25) -> list[dict]:
    with sqlite3.connect(DB_PATH) as c:
        c.row_factory = sqlite3.Row
        rows = c.execute(
            """SELECT id, symbol, body, tags, pinned, created_at, updated_at
               FROM notes ORDER BY created_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
