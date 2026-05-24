import sqlite3
import json

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
                id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                phone              TEXT NOT NULL,
                guest_name         TEXT,
                client_type        TEXT,
                interests          TEXT,
                arrival_medium     TEXT,
                check_in           DATE NOT NULL,
                check_out          DATE NOT NULL,
                room_type          TEXT,
                rooms_count        INTEGER DEFAULT 1,
                pax                INTEGER,
                food_preferences   TEXT,
                meal_plan          TEXT DEFAULT 'No Meals',
                meal_location      TEXT DEFAULT 'In-house',
                activities         TEXT,
                transport          TEXT,
                internal_transport TEXT,
                total_amount       INTEGER,
                status             TEXT DEFAULT 'confirmed',
                created_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # Seed rooms if empty
        if conn.execute("SELECT COUNT(*) FROM rooms").fetchone()[0] == 0:
            conn.executemany(
                "INSERT INTO rooms (id, name, type) VALUES (?, ?, ?)",
                [(1, "Room 1", "deluxe"), (2, "Room 2", "deluxe"),
                 (3, "Room 3", "standard"), (4, "Room 4", "standard")],
            )

        # Migration: add any new columns that don't exist yet
        existing = {row[1] for row in conn.execute("PRAGMA table_info(bookings)").fetchall()}
        new_cols = [
            ("client_type",        "TEXT"),
            ("interests",          "TEXT"),
            ("arrival_medium",     "TEXT"),
            ("food_preferences",   "TEXT"),
            ("meal_plan",          "TEXT DEFAULT 'No Meals'"),
            ("meal_location",      "TEXT DEFAULT 'In-house'"),
            ("internal_transport", "TEXT"),
        ]
        for col, defn in new_cols:
            if col not in existing:
                conn.execute(f"ALTER TABLE bookings ADD COLUMN {col} {defn}")


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
    phone:              str,
    check_in:           str,
    check_out:          str,
    room_type:          str,
    rooms_count:        int,
    pax:                int,
    activities:         list,
    transport:          "str | None",
    total_amount:       int,
    guest_name:         "str | None" = None,
    client_type:        "str | None" = None,
    interests:          "str | None" = None,
    arrival_medium:     "str | None" = None,
    food_preferences:   "str | None" = None,
    meal_plan:          str = "No Meals",
    meal_location:      str = "In-house",
    internal_transport: "str | None" = None,
) -> int:
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO bookings
                (phone, guest_name, client_type, interests, arrival_medium,
                 check_in, check_out, room_type, rooms_count, pax,
                 food_preferences, meal_plan, meal_location,
                 activities, transport, internal_transport, total_amount)
            VALUES (?, ?, ?, ?, ?,  ?, ?, ?, ?, ?,  ?, ?, ?,  ?, ?, ?, ?)
            """,
            (phone, guest_name, client_type, interests, arrival_medium,
             check_in, check_out, room_type, rooms_count, pax,
             food_preferences, meal_plan, meal_location,
             json.dumps(activities), transport, internal_transport, total_amount),
        )
    return cur.lastrowid


def get_bookings_by_phone(phone: str) -> list:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM bookings WHERE phone = ? ORDER BY created_at DESC",
            (phone,),
        ).fetchall()
    return [dict(r) for r in rows]
