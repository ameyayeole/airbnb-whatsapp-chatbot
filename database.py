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


def _connect():
    """
    Try the DATABASE_URL as-is first (works when the server has IPv4 or
    a pooler URL is configured).  If libpq can't resolve the hostname
    (Supabase free-tier direct connections are IPv6-only), fall back to
    resolving the AAAA record with Python's socket and substituting the
    literal IPv6 address — which works on IPv6-capable hosts (e.g. macOS).
    On IPv4-only hosts (e.g. Render free tier) the caller will get a clear
    error pointing to the pooler fix.
    """
    try:
        return psycopg2.connect(DATABASE_URL)
    except psycopg2.OperationalError as first_err:
        err_str = str(first_err)
        if "could not translate host name" not in err_str:
            raise  # real connection error — re-raise immediately

        # DNS failed → try IPv6 resolution via Python's socket
        m = re.search(r"@([^:/\[]+)(:\d+)", DATABASE_URL)
        if not m:
            raise
        hostname = m.group(1)
        try:
            addrs = socket.getaddrinfo(hostname, None, socket.AF_INET6, socket.SOCK_STREAM)
            if not addrs:
                raise first_err
            ipv6 = addrs[0][4][0]
            ipv6_url = DATABASE_URL.replace(f"@{hostname}", f"@[{ipv6}]")
            return psycopg2.connect(ipv6_url)
        except psycopg2.OperationalError as ipv6_err:
            if "Network is unreachable" in str(ipv6_err) or "Connection refused" in str(ipv6_err):
                raise psycopg2.OperationalError(
                    "Cannot reach Supabase via IPv4 or IPv6.\n"
                    "Fix: set DATABASE_URL to the Supabase *pooler* URL.\n"
                    "Dashboard → Settings → Database → Connection pooling → copy URI."
                ) from ipv6_err
            raise ipv6_err
        except Exception:
            raise first_err


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
                    room_count       INTEGER DEFAULT 1,
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
                ("room_count",       "INTEGER DEFAULT 1"),
            ]
            for col, defn in new_cols:
                cur.execute(f"ALTER TABLE bookings ADD COLUMN IF NOT EXISTS {col} {defn}")

        conn.commit()
    finally:
        conn.close()


def check_availability(check_in: str, check_out: str, room_type: str, rooms_requested: int = 1) -> bool:
    """Return True if rooms_requested of room_type are available for the date range."""
    from pricing import ROOM_INVENTORY
    total_inventory = ROOM_INVENTORY.get(room_type, 1)
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COALESCE(SUM(room_count), 0) FROM bookings
                WHERE  status    != 'cancelled'
                  AND  room_type  = %s
                  AND  check_in   < %s
                  AND  check_out  > %s
            """, (room_type, check_out, check_in))
            already_booked = cur.fetchone()[0]
            return (already_booked + rooms_requested) <= total_inventory
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
    room_count:      int,
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
                     check_in, check_out, nights, special_requests, room_type, room_count,
                     food_preference, veg_count, nv_count,
                     meal_plan_d1, meal_plan_sub,
                     arrival_mode, pickup_point, vehicle_type,
                     activities_d1, activities_d2,
                     total_amount, advance_amount)
                VALUES
                    (%s,%s,%s,%s,%s, %s,%s,%s,%s,%s,%s, %s,%s,%s, %s,%s, %s,%s,%s, %s,%s, %s,%s)
                RETURNING id
            """, (
                phone, guest_name, email, adults, children,
                check_in, check_out, nights, special_requests, room_type, room_count,
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
