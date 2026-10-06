"""Shift log of pages triaged on the desk."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STATUSES = ("open", "acknowledged", "resolved")


def connect(path: Path) -> sqlite3.Connection:
    """Open the shift log and create it on first use."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS pages (
            id INTEGER PRIMARY KEY,
            created_at TEXT NOT NULL,
            text TEXT NOT NULL,
            title TEXT NOT NULL,
            status TEXT NOT NULL,
            checks TEXT NOT NULL,
            card TEXT NOT NULL
        )
        """
    )
    return conn


def _title(card: dict[str, Any]) -> str:
    head = str(card.get("host") or card.get("service") or "Unlinked page")
    symptom = str(card.get("symptom") or "")
    if symptom:
        return f"{head} · {symptom}"
    return head


def _row_to_page(row: sqlite3.Row) -> dict[str, Any]:
    card = json.loads(row["card"])
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "text": row["text"],
        "title": row["title"],
        "status": row["status"],
        "checks": json.loads(row["checks"]),
        "card": card,
    }


def _summary(page: dict[str, Any]) -> dict[str, Any]:
    card = page["card"]
    return {
        "id": page["id"],
        "created_at": page["created_at"],
        "title": page["title"],
        "status": page["status"],
        "host": card.get("host") or "",
        "service": card.get("service") or "",
        "symptom": card.get("symptom") or "",
    }


def add_page(path: Path, card: dict[str, Any]) -> dict[str, Any]:
    """Store a new open page. Checks start unchecked."""
    checklist = list(card.get("checklist") or [])
    checks = [False for _step in checklist]
    created = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with connect(path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO pages (created_at, text, title, status, checks, card)
            VALUES (?, ?, ?, 'open', ?, ?)
            """,
            (
                created,
                str(card.get("text") or ""),
                _title(card),
                json.dumps(checks),
                json.dumps(card),
            ),
        )
        page_id = int(cursor.lastrowid or 0)
    loaded = get_page(path, page_id)
    if loaded is None:
        raise RuntimeError("stored page could not be read back")
    return loaded


def list_pages(path: Path, limit: int = 40) -> list[dict[str, Any]]:
    """Newest pages first, without the full card body."""
    if not path.exists():
        return []
    with connect(path) as conn:
        rows = conn.execute(
            "SELECT * FROM pages ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [_summary(_row_to_page(row)) for row in rows]


def get_page(path: Path, page_id: int) -> dict[str, Any] | None:
    """Return one page, or None when the id is unknown."""
    if not path.exists():
        return None
    with connect(path) as conn:
        row = conn.execute("SELECT * FROM pages WHERE id = ?", (page_id,)).fetchone()
    if row is None:
        return None
    return _row_to_page(row)


def update_page(
    path: Path,
    page_id: int,
    *,
    status: str | None = None,
    checks: list[bool] | None = None,
) -> dict[str, Any] | None:
    """Change status or checklist marks. The card itself stays as triaged."""
    current = get_page(path, page_id)
    if current is None:
        return None
    next_status = current["status"] if status is None else status
    if next_status not in STATUSES:
        raise ValueError(f"status must be one of {', '.join(STATUSES)}")
    next_checks = current["checks"] if checks is None else checks
    expected = len(current["card"].get("checklist") or [])
    if len(next_checks) != expected or any(not isinstance(item, bool) for item in next_checks):
        raise ValueError("checks must be one boolean per checklist step")
    with connect(path) as conn:
        conn.execute(
            "UPDATE pages SET status = ?, checks = ? WHERE id = ?",
            (next_status, json.dumps(next_checks), page_id),
        )
    return get_page(path, page_id)
