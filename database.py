import sqlite3
import json
from datetime import date

DB_PATH = "farmhouse.db"


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _connect() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS rooms (
                id   INTEGER PRIMARY KEY,
                name TEXT,
                type TEXT
            );

            CREATE TABLE IF NOT EXISTS bookings (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                phone        TEXT NOT NULL,
                guest_name   TEXT,
                check_in     DATE NOT NULL,
                check_out    DATE NOT NULL,
                room_type    TEXT,
                rooms_count  INTEGER DEFAULT 1,
                pax          INTEGER,
                activities   TEXT,
                transport    TEXT,
                total_amount INTEGER,
                status       TEXT DEFAULT 'confirmed',
                created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        if conn.execute("SELECT COUNT(*) FROM rooms").fetchone()[0] == 0:
            conn.executemany(
                "INSERT INTO rooms (id, name, type) VALUES (?, ?, ?)",
                [(1, "Room 1", "couple"), (2, "Room 2", "couple"),
                 (3, "Room 3", "bulk"),  (4, "Room 4", "bulk")],
            )


def check_availability(check_in: str, check_out: str, rooms_needed: int) -> bool:
    """Return True if rooms_needed rooms are free for the given date range."""
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT COALESCE(SUM(rooms_count), 0) AS booked
            FROM bookings
            WHERE status = 'confirmed'
              AND check_in  < ?
              AND check_out > ?
            """,
            (check_out, check_in),
        ).fetchone()
    return (row["booked"] + rooms_needed) <= 4


def create_booking(
    phone: str,
    check_in: str,
    check_out: str,
    room_type: str,
    rooms_count: int,
    pax: int,
    activities: list[str],
    transport: str | None,
    total_amount: int,
    guest_name: str | None = None,
) -> int:
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO bookings
                (phone, guest_name, check_in, check_out, room_type,
                 rooms_count, pax, activities, transport, total_amount)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (phone, guest_name, check_in, check_out, room_type,
             rooms_count, pax, json.dumps(activities), transport, total_amount),
        )
    return cur.lastrowid


def get_bookings_by_phone(phone: str) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM bookings WHERE phone = ? ORDER BY created_at DESC",
            (phone,),
        ).fetchall()
    return [dict(r) for r in rows]
