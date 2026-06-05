"""
database.py — Supabase / PostgreSQL backend for Mondkar Farm Stay
"""
import os
import re
import json
import socket
from datetime import date as _date
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ["DATABASE_URL"]


def _resolve_ipv6(url: str) -> str:
    """
    libpq (the C layer in psycopg2) only resolves IPv4 A-records.
    Supabase free-tier projects are IPv6-only by default.
    Python's socket.getaddrinfo() resolves AAAA records correctly,
    so we pre-resolve the hostname and substitute the literal IPv6
    address (bracket-enclosed, as RFC 3986 requires).
    """
    # Match host in postgresql://user:pass@HOST:port/db
    m = re.search(r"@([^:/\[]+)(:\d+)", url)
    if not m:
        return url
    hostname = m.group(1)
    try:
        addrs = socket.getaddrinfo(hostname, None, socket.AF_INET6, socket.SOCK_STREAM)
        if addrs:
            ipv6 = addrs[0][4][0]
            url  = url.replace(f"@{hostname}", f"@[{ipv6}]")
    except Exception:
        pass  # hostname might already be IPv4 or direct IP — leave as-is
    return url


_RESOLVED_URL = _resolve_ipv6(DATABASE_URL)


def _connect():
    return psycopg2.connect(_RESOLVED_URL)


def init_db():
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS bookings (
                    id               SERIAL PRIMARY KEY,
                    booking_ref      TEXT,
                    phone            TEXT NOT NULL,
                    guest_name       TEXT,
                    email            TEXT,
                    adults           INTEGER DEFAULT 1,
                    children         INTEGER DEFAULT 0,
                    check_in         DATE NOT NULL,
                    check_out        DATE NOT NULL,
                    nights           INTEGER,
                    special_requests TEXT,
                    room_type        TEXT,
                    food_preference  TEXT,
                    veg_count        INTEGER DEFAULT 0,
                    nv_count         INTEGER DEFAULT 0,
                    meal_plan_d1     TEXT DEFAULT 'No Meals',
                    meal_plan_sub    TEXT DEFAULT 'No Meals',
                    arrival_mode     TEXT,
                    pickup_point     TEXT,
                    vehicle_type     TEXT,
                    activities_d1    TEXT,
                    activities_d2    TEXT,
                    total_amount     INTEGER,
                    advance_amount   INTEGER,
                    status           TEXT DEFAULT 'pending_payment',
                    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            new_cols = [
                ("booking_ref",      "TEXT"),
                ("email",            "TEXT"),
                ("adults",           "INTEGER DEFAULT 1"),
                ("children",         "INTEGER DEFAULT 0"),
                ("nights",           "INTEGER"),
                ("special_requests", "TEXT"),
                ("food_preference",  "TEXT"),
                ("veg_count",        "INTEGER DEFAULT 0"),
                ("nv_count",         "INTEGER DEFAULT 0"),
                ("meal_plan_d1",     "TEXT DEFAULT 'No Meals'"),
                ("meal_plan_sub",    "TEXT DEFAULT 'No Meals'"),
                ("arrival_mode",     "TEXT"),
                ("pickup_point",     "TEXT"),
                ("vehicle_type",     "TEXT"),
                ("activities_d1",    "TEXT"),
                ("activities_d2",    "TEXT"),
                ("advance_amount",   "INTEGER"),
            ]
            for col, defn in new_cols:
                cur.execute(f"ALTER TABLE bookings ADD COLUMN IF NOT EXISTS {col} {defn}")

        conn.commit()
    finally:
        conn.close()


def check_availability(check_in: str, check_out: str, room_type: str) -> bool:
    """Return True if the room type has no confirmed booking in this date range."""
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) FROM bookings
                WHERE  status    != 'cancelled'
                  AND  room_type  = %s
                  AND  check_in   < %s
                  AND  check_out  > %s
            """, (room_type, check_out, check_in))
            return cur.fetchone()[0] == 0
    finally:
        conn.close()


def create_booking(
    phone:           str,
    guest_name:      str,
    email:           "str | None",
    adults:          int,
    children:        int,
    check_in:        str,
    check_out:       str,
    nights:          int,
    special_requests:"str | None",
    room_type:       str,
    food_preference: str,
    veg_count:       int,
    nv_count:        int,
    meal_plan_d1:    str,
    meal_plan_sub:   str,
    arrival_mode:    "str | None",
    pickup_point:    "str | None",
    vehicle_type:    "str | None",
    activities_d1:   list,
    activities_d2:   list,
    total_amount:    int,
    advance_amount:  int,
) -> tuple:
    """Returns (booking_id: int, booking_ref: str)."""
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO bookings
                    (phone, guest_name, email, adults, children,
                     check_in, check_out, nights, special_requests, room_type,
                     food_preference, veg_count, nv_count,
                     meal_plan_d1, meal_plan_sub,
                     arrival_mode, pickup_point, vehicle_type,
                     activities_d1, activities_d2,
                     total_amount, advance_amount)
                VALUES
                    (%s,%s,%s,%s,%s, %s,%s,%s,%s,%s, %s,%s,%s, %s,%s, %s,%s,%s, %s,%s, %s,%s)
                RETURNING id
            """, (
                phone, guest_name, email, adults, children,
                check_in, check_out, nights, special_requests, room_type,
                food_preference, veg_count, nv_count,
                meal_plan_d1, meal_plan_sub,
                arrival_mode, pickup_point, vehicle_type,
                json.dumps(activities_d1), json.dumps(activities_d2),
                total_amount, advance_amount,
            ))
            booking_id = cur.fetchone()[0]

            # Generate human-readable ref: MFS-YYYYMMDD-0001
            ref = f"MFS-{_date.today().strftime('%Y%m%d')}-{booking_id:04d}"
            cur.execute("UPDATE bookings SET booking_ref = %s WHERE id = %s", (ref, booking_id))

        conn.commit()
        return booking_id, ref
    finally:
        conn.close()


def get_bookings_by_phone(phone: str) -> list:
    conn = _connect()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM bookings WHERE phone = %s ORDER BY created_at DESC",
                (phone,),
            )
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()
