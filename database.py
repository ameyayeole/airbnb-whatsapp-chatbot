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
                ("booking_ref",       "TEXT"),
                ("email",             "TEXT"),
                ("adults",            "INTEGER DEFAULT 1"),
                ("children",          "INTEGER DEFAULT 0"),
                ("nights",            "INTEGER"),
                ("special_requests",  "TEXT"),
                ("food_preference",   "TEXT"),
                ("veg_count",         "INTEGER DEFAULT 0"),
                ("nv_count",          "INTEGER DEFAULT 0"),
                ("meal_plan_d1",      "TEXT DEFAULT 'No Meals'"),
                ("meal_plan_sub",     "TEXT DEFAULT 'No Meals'"),
                ("arrival_mode",      "TEXT"),
                ("pickup_point",      "TEXT"),
                ("vehicle_type",      "TEXT"),
                ("acknowledged_at",   "TIMESTAMP"),
                ("payment_proof",     "TEXT"),
                ("activities_d1",    "TEXT"),
                ("activities_d2",    "TEXT"),
                ("advance_amount",   "INTEGER"),
                ("room_count",       "INTEGER DEFAULT 1"),
            ]
            for col, defn in new_cols:
                cur.execute(f"ALTER TABLE bookings ADD COLUMN IF NOT EXISTS {col} {defn}")

            cur.execute("""
                CREATE TABLE IF NOT EXISTS booking_tokens (
                    token       TEXT PRIMARY KEY,
                    phone       TEXT NOT NULL,
                    guest_name  TEXT NOT NULL,
                    email       TEXT NOT NULL,
                    used        BOOLEAN DEFAULT FALSE,
                    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # ── configurable content tables ──────────────────────────────────
            cur.execute("""
                CREATE TABLE IF NOT EXISTS kv_settings (
                    key   TEXT PRIMARY KEY,
                    value TEXT
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS room_types (
                    id          SERIAL PRIMARY KEY,
                    key         TEXT UNIQUE NOT NULL,
                    name        TEXT NOT NULL,
                    rate        INTEGER NOT NULL,
                    capacity    INTEGER NOT NULL,
                    inventory   INTEGER NOT NULL DEFAULT 1,
                    description TEXT,
                    photo_path  TEXT,
                    sort_order  INTEGER DEFAULT 0,
                    active      BOOLEAN DEFAULT TRUE
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS meal_plans (
                    id         SERIAL PRIMARY KEY,
                    key        TEXT UNIQUE NOT NULL,
                    name       TEXT NOT NULL,
                    price      INTEGER NOT NULL DEFAULT 0,
                    sort_order INTEGER DEFAULT 0,
                    active     BOOLEAN DEFAULT TRUE
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS activities (
                    id         SERIAL PRIMARY KEY,
                    day        TEXT NOT NULL,
                    key        TEXT UNIQUE NOT NULL,
                    name       TEXT NOT NULL,
                    price      INTEGER NOT NULL DEFAULT 0,
                    per_unit   TEXT NOT NULL DEFAULT 'group',
                    duration   TEXT,
                    note       TEXT,
                    is_free    BOOLEAN DEFAULT FALSE,
                    sort_order INTEGER DEFAULT 0,
                    active     BOOLEAN DEFAULT TRUE
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS pickup_points (
                    id         SERIAL PRIMARY KEY,
                    name       TEXT UNIQUE NOT NULL,
                    base_fare  INTEGER NOT NULL DEFAULT 0,
                    sort_order INTEGER DEFAULT 0,
                    active     BOOLEAN DEFAULT TRUE
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS vehicle_types (
                    id          SERIAL PRIMARY KEY,
                    key         TEXT UNIQUE NOT NULL,
                    name        TEXT NOT NULL,
                    multiplier  REAL NOT NULL DEFAULT 1.0,
                    description TEXT,
                    sort_order  INTEGER DEFAULT 0,
                    active      BOOLEAN DEFAULT TRUE
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS photos (
                    id         SERIAL PRIMARY KEY,
                    slot       TEXT NOT NULL,
                    filename   TEXT NOT NULL,
                    alt_text   TEXT,
                    sort_order INTEGER DEFAULT 0,
                    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS photos_slot_idx ON photos (slot, sort_order)")

            # ── feedback ────────────────────────────────────────────────────
            cur.execute("""
                CREATE TABLE IF NOT EXISTS feedback_tokens (
                    token       TEXT PRIMARY KEY,
                    booking_id  INTEGER NOT NULL,
                    used        BOOLEAN DEFAULT FALSE,
                    sent_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    used_at     TIMESTAMP
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS feedback (
                    id          SERIAL PRIMARY KEY,
                    booking_id  INTEGER,
                    booking_ref TEXT,
                    guest_name  TEXT,
                    rating      INTEGER NOT NULL,
                    comment     TEXT,
                    status      TEXT DEFAULT 'pending',
                    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    approved_at TIMESTAMP
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS feedback_media (
                    id          SERIAL PRIMARY KEY,
                    feedback_id INTEGER NOT NULL,
                    filename    TEXT NOT NULL,
                    kind        TEXT NOT NULL DEFAULT 'image',
                    approved    BOOLEAN DEFAULT FALSE,
                    sort_order  INTEGER DEFAULT 0,
                    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cur.execute("ALTER TABLE bookings ADD COLUMN IF NOT EXISTS feedback_sent_at TIMESTAMP")

        conn.commit()
        _seed_defaults_if_empty()
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════════════
# SEED DEFAULTS (only runs when tables are empty)
# ═══════════════════════════════════════════════════════════════════════════════

_DEFAULT_KV = {
    "property_name":       "Mondkar Farm Stay",
    "property_address":    "Mondys Farm Stay, Sindhudurg, Maharashtra",
    "property_gps":        "https://maps.google.com/?q=16.0,73.7",
    "property_contact":    "+91-XXXXXXXXXX",
    "support_email":       "stay@mondys.in",
    "advance_percent":     "50",
    "check_in_time":       "1:00 PM",
    "check_out_time":      "12:00 PM (Noon)",
    "upi_vpa":             "",
    "payment_qr_filename": "",
    "owner_wa_numbers":    "",
    "cancellation_policy": (
        "50% advance at time of booking.\n"
        "50% refund if cancelled 7+ days before check-in.\n"
        "Zero refund within 7 days of check-in.\n"
        "Partial cancellations allowed (by days / rooms / guests)."
    ),
    "transport_contact":    "+91-XXXXXXXXXX (Farm Driver)",
    "tour_guide_contact":   "+91-XXXXXXXXXX (Local Guide)",
    "sports_guide_contact": "+91-XXXXXXXXXX (Water Sports)",
    "nearest_hospital":     "District Hospital, Sindhudurg — 12 km",
    "medical_contact":      "+91-XXXXXXXXXX",
    "ambulance":            "108 (free national ambulance)",
    "pharmacy_info":        "Pharmacy 2 km away. First-aid kit on premises.",
}

_DEFAULT_ROOMS = [
    {"key": "family_suite",   "name": "Family Suite",   "rate": 6000, "capacity": 4, "inventory": 2,
     "description": "A private suite for the whole family — comfortable double plus space for kids, orchard view.", "sort_order": 1},
    {"key": "dormitory_stay", "name": "Dormitory Stay", "rate": 4000, "capacity": 6, "inventory": 2,
     "description": "Six bunks in one airy room — great for friend groups, trekking weekends and late-night card games.", "sort_order": 2},
]

_DEFAULT_MEALS = [
    {"key": "bld",  "name": "All Meals (BLD)",    "price": 950, "sort_order": 1},
    {"key": "ld",   "name": "Lunch+Dinner",       "price": 750, "sort_order": 2},
    {"key": "bd",   "name": "Breakfast+Dinner",   "price": 600, "sort_order": 3},
    {"key": "d",    "name": "Dinner Only",        "price": 400, "sort_order": 4},
    {"key": "b",    "name": "Breakfast Only",     "price": 200, "sort_order": 5},
    {"key": "none", "name": "No Meals",           "price":   0, "sort_order": 6},
]

_DEFAULT_ACTIVITIES = [
    # day 1 — on-farm
    {"day": "d1", "key": "petting",  "name": "Animal Petting",            "price":   0, "per_unit": "group",  "duration": "1 hour",    "is_free": True,  "note": "",                             "sort_order": 1},
    {"day": "d1", "key": "bullock",  "name": "Bullock Cart Ride",         "price": 100, "per_unit": "person", "duration": "15 mins",   "is_free": False, "note": "",                             "sort_order": 2},
    {"day": "d1", "key": "breakfast","name": "Pick Your Breakfast Plate", "price": 300, "per_unit": "person", "duration": "30 mins",   "is_free": False, "note": "",                             "sort_order": 3},
    {"day": "d1", "key": "trek",     "name": "Trekking",                  "price":   0, "per_unit": "group",  "duration": "2 hours",   "is_free": True,  "note": "",                             "sort_order": 4},
    {"day": "d1", "key": "pool",     "name": "Swimming Pool",             "price":   0, "per_unit": "group",  "duration": "All day",   "is_free": True,  "note": "",                             "sort_order": 5},
    {"day": "d1", "key": "rain",     "name": "Gazebo Rain Dance",         "price": 150, "per_unit": "person", "duration": "2 hours",   "is_free": False, "note": "",                             "sort_order": 6},
    {"day": "d1", "key": "games",    "name": "Indoor Games",              "price": 150, "per_unit": "person", "duration": "3-4 hours", "is_free": False, "note": "",                             "sort_order": 7},
    # day 2 — off-farm
    {"day": "d2", "key": "kayak",    "name": "Kayaking",                  "price": 400, "per_unit": "boat",   "duration": "1 hour",    "is_free": False, "note": "",                             "sort_order": 1},
    {"day": "d2", "key": "beach",    "name": "Beach & Temple Visit",      "price":   0, "per_unit": "group",  "duration": "Half day",  "is_free": True,  "note": "Transport charges apply",      "sort_order": 2},
    {"day": "d2", "key": "malvan",   "name": "Malvan Water Sports",       "price":   0, "per_unit": "group",  "duration": "Half day",  "is_free": True,  "note": "Local fare applies",           "sort_order": 3},
    {"day": "d2", "key": "vengurla", "name": "Vengurla Beach",            "price":   0, "per_unit": "group",  "duration": "Half day",  "is_free": True,  "note": "Transport charges apply",      "sort_order": 4},
]

_DEFAULT_PICKUP_POINTS = [
    {"name": "Kudal Railway Station",      "base_fare": 500, "sort_order": 1},
    {"name": "Sawantwadi Railway Station", "base_fare": 600, "sort_order": 2},
    {"name": "Chipi Airport",              "base_fare": 700, "sort_order": 3},
    {"name": "Mopa Airport",               "base_fare": 800, "sort_order": 4},
]

_DEFAULT_VEHICLES = [
    {"key": "sedan",   "name": "Sedan",       "multiplier": 1.0, "description": "4-seater car",          "sort_order": 1},
    {"key": "muv",     "name": "MUV",         "multiplier": 1.5, "description": "6-7 seater MUV",        "sort_order": 2},
    {"key": "charter", "name": "Charter Bus", "multiplier": 3.0, "description": "Large group (20+ pax)", "sort_order": 3},
]


def _seed_defaults_if_empty() -> None:
    """Populate config tables on first run. Idempotent — does nothing if table has rows."""
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM kv_settings")
            if cur.fetchone()[0] == 0:
                for k, v in _DEFAULT_KV.items():
                    cur.execute("INSERT INTO kv_settings (key, value) VALUES (%s, %s) ON CONFLICT DO NOTHING", (k, v))

            cur.execute("SELECT COUNT(*) FROM room_types")
            if cur.fetchone()[0] == 0:
                for r in _DEFAULT_ROOMS:
                    cur.execute("""
                        INSERT INTO room_types (key, name, rate, capacity, inventory, description, sort_order)
                        VALUES (%(key)s, %(name)s, %(rate)s, %(capacity)s, %(inventory)s, %(description)s, %(sort_order)s)
                        ON CONFLICT (key) DO NOTHING
                    """, r)

            cur.execute("SELECT COUNT(*) FROM meal_plans")
            if cur.fetchone()[0] == 0:
                for m in _DEFAULT_MEALS:
                    cur.execute("""
                        INSERT INTO meal_plans (key, name, price, sort_order) VALUES (%(key)s, %(name)s, %(price)s, %(sort_order)s)
                        ON CONFLICT (key) DO NOTHING
                    """, m)

            cur.execute("SELECT COUNT(*) FROM activities")
            if cur.fetchone()[0] == 0:
                for a in _DEFAULT_ACTIVITIES:
                    cur.execute("""
                        INSERT INTO activities (day, key, name, price, per_unit, duration, note, is_free, sort_order)
                        VALUES (%(day)s, %(key)s, %(name)s, %(price)s, %(per_unit)s, %(duration)s, %(note)s, %(is_free)s, %(sort_order)s)
                        ON CONFLICT (key) DO NOTHING
                    """, a)

            cur.execute("SELECT COUNT(*) FROM pickup_points")
            if cur.fetchone()[0] == 0:
                for p in _DEFAULT_PICKUP_POINTS:
                    cur.execute("""
                        INSERT INTO pickup_points (name, base_fare, sort_order) VALUES (%(name)s, %(base_fare)s, %(sort_order)s)
                        ON CONFLICT (name) DO NOTHING
                    """, p)

            cur.execute("SELECT COUNT(*) FROM vehicle_types")
            if cur.fetchone()[0] == 0:
                for v in _DEFAULT_VEHICLES:
                    cur.execute("""
                        INSERT INTO vehicle_types (key, name, multiplier, description, sort_order)
                        VALUES (%(key)s, %(name)s, %(multiplier)s, %(description)s, %(sort_order)s)
                        ON CONFLICT (key) DO NOTHING
                    """, v)

        conn.commit()
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════════════
# SETTINGS HELPERS (used by web, bot, pricing)
# ═══════════════════════════════════════════════════════════════════════════════

def get_setting(key: str, default: str = "") -> str:
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT value FROM kv_settings WHERE key = %s", (key,))
            row = cur.fetchone()
            return row[0] if row and row[0] is not None else default
    finally:
        conn.close()


def get_all_settings() -> dict:
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT key, value FROM kv_settings")
            return {k: (v or "") for k, v in cur.fetchall()}
    finally:
        conn.close()


def set_setting(key: str, value: str) -> None:
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO kv_settings (key, value) VALUES (%s, %s)
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
            """, (key, value))
        conn.commit()
    finally:
        conn.close()


def list_rooms(active_only: bool = True) -> list:
    conn = _connect()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            q = "SELECT * FROM room_types"
            if active_only:
                q += " WHERE active = TRUE"
            q += " ORDER BY sort_order, id"
            cur.execute(q)
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def get_room_by_name(name: str) -> "dict | None":
    conn = _connect()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM room_types WHERE name = %s", (name,))
            row = cur.fetchone()
            return dict(row) if row else None
    finally:
        conn.close()


def upsert_room(key: str, name: str, rate: int, capacity: int, inventory: int,
                description: str = "", sort_order: int = 0, active: bool = True,
                room_id: "int | None" = None) -> None:
    conn = _connect()
    try:
        with conn.cursor() as cur:
            if room_id:
                cur.execute("""
                    UPDATE room_types SET key=%s, name=%s, rate=%s, capacity=%s,
                        inventory=%s, description=%s, sort_order=%s, active=%s
                    WHERE id=%s
                """, (key, name, rate, capacity, inventory, description, sort_order, active, room_id))
            else:
                cur.execute("""
                    INSERT INTO room_types (key, name, rate, capacity, inventory, description, sort_order, active)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, (key, name, rate, capacity, inventory, description, sort_order, active))
        conn.commit()
    finally:
        conn.close()


def delete_room(room_id: int) -> None:
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM room_types WHERE id = %s", (room_id,))
        conn.commit()
    finally:
        conn.close()


def list_meal_plans(active_only: bool = True) -> list:
    conn = _connect()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            q = "SELECT * FROM meal_plans"
            if active_only:
                q += " WHERE active = TRUE"
            q += " ORDER BY sort_order, id"
            cur.execute(q)
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def upsert_meal_plan(key: str, name: str, price: int, sort_order: int = 0,
                     active: bool = True, plan_id: "int | None" = None) -> None:
    conn = _connect()
    try:
        with conn.cursor() as cur:
            if plan_id:
                cur.execute("UPDATE meal_plans SET key=%s, name=%s, price=%s, sort_order=%s, active=%s WHERE id=%s",
                            (key, name, price, sort_order, active, plan_id))
            else:
                cur.execute("INSERT INTO meal_plans (key, name, price, sort_order, active) VALUES (%s, %s, %s, %s, %s)",
                            (key, name, price, sort_order, active))
        conn.commit()
    finally:
        conn.close()


def delete_meal_plan(plan_id: int) -> None:
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM meal_plans WHERE id = %s", (plan_id,))
        conn.commit()
    finally:
        conn.close()


def list_activities(day: "str | None" = None, active_only: bool = True) -> list:
    conn = _connect()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            q = "SELECT * FROM activities WHERE 1=1"
            params = []
            if day:
                q += " AND day = %s"
                params.append(day)
            if active_only:
                q += " AND active = TRUE"
            q += " ORDER BY day, sort_order, id"
            cur.execute(q, params)
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def upsert_activity(day: str, key: str, name: str, price: int, per_unit: str,
                    duration: str = "", note: str = "", is_free: bool = False,
                    sort_order: int = 0, active: bool = True,
                    activity_id: "int | None" = None) -> None:
    conn = _connect()
    try:
        with conn.cursor() as cur:
            if activity_id:
                cur.execute("""
                    UPDATE activities SET day=%s, key=%s, name=%s, price=%s, per_unit=%s,
                        duration=%s, note=%s, is_free=%s, sort_order=%s, active=%s
                    WHERE id=%s
                """, (day, key, name, price, per_unit, duration, note, is_free, sort_order, active, activity_id))
            else:
                cur.execute("""
                    INSERT INTO activities (day, key, name, price, per_unit, duration, note, is_free, sort_order, active)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (day, key, name, price, per_unit, duration, note, is_free, sort_order, active))
        conn.commit()
    finally:
        conn.close()


def delete_activity(activity_id: int) -> None:
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM activities WHERE id = %s", (activity_id,))
        conn.commit()
    finally:
        conn.close()


def list_pickup_points(active_only: bool = True) -> list:
    conn = _connect()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            q = "SELECT * FROM pickup_points"
            if active_only:
                q += " WHERE active = TRUE"
            q += " ORDER BY sort_order, id"
            cur.execute(q)
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def upsert_pickup_point(name: str, base_fare: int, sort_order: int = 0,
                        active: bool = True, point_id: "int | None" = None) -> None:
    conn = _connect()
    try:
        with conn.cursor() as cur:
            if point_id:
                cur.execute("UPDATE pickup_points SET name=%s, base_fare=%s, sort_order=%s, active=%s WHERE id=%s",
                            (name, base_fare, sort_order, active, point_id))
            else:
                cur.execute("INSERT INTO pickup_points (name, base_fare, sort_order, active) VALUES (%s, %s, %s, %s)",
                            (name, base_fare, sort_order, active))
        conn.commit()
    finally:
        conn.close()


def delete_pickup_point(point_id: int) -> None:
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM pickup_points WHERE id = %s", (point_id,))
        conn.commit()
    finally:
        conn.close()


def list_vehicle_types(active_only: bool = True) -> list:
    conn = _connect()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            q = "SELECT * FROM vehicle_types"
            if active_only:
                q += " WHERE active = TRUE"
            q += " ORDER BY sort_order, id"
            cur.execute(q)
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def upsert_vehicle(key: str, name: str, multiplier: float, description: str = "",
                   sort_order: int = 0, active: bool = True,
                   vehicle_id: "int | None" = None) -> None:
    conn = _connect()
    try:
        with conn.cursor() as cur:
            if vehicle_id:
                cur.execute("""
                    UPDATE vehicle_types SET key=%s, name=%s, multiplier=%s, description=%s,
                        sort_order=%s, active=%s WHERE id=%s
                """, (key, name, multiplier, description, sort_order, active, vehicle_id))
            else:
                cur.execute("""
                    INSERT INTO vehicle_types (key, name, multiplier, description, sort_order, active)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (key, name, multiplier, description, sort_order, active))
        conn.commit()
    finally:
        conn.close()


def delete_vehicle(vehicle_id: int) -> None:
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM vehicle_types WHERE id = %s", (vehicle_id,))
        conn.commit()
    finally:
        conn.close()


def list_photos(slot: "str | None" = None) -> list:
    conn = _connect()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if slot:
                cur.execute("SELECT * FROM photos WHERE slot=%s ORDER BY sort_order, id", (slot,))
            else:
                cur.execute("SELECT * FROM photos ORDER BY slot, sort_order, id")
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def add_photo(slot: str, filename: str, alt_text: str = "", sort_order: int = 0) -> int:
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO photos (slot, filename, alt_text, sort_order)
                VALUES (%s, %s, %s, %s) RETURNING id
            """, (slot, filename, alt_text, sort_order))
            return cur.fetchone()[0]
    finally:
        conn.commit()
        conn.close()


def delete_photo(photo_id: int) -> "str | None":
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM photos WHERE id=%s RETURNING filename", (photo_id,))
            row = cur.fetchone()
        conn.commit()
        return row[0] if row else None
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════════════
# BOOKING STATUS WORKFLOW
# ═══════════════════════════════════════════════════════════════════════════════

def list_bookings(status: "str | None" = None, limit: int = 200) -> list:
    conn = _connect()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if status:
                cur.execute("SELECT * FROM bookings WHERE status=%s ORDER BY created_at DESC LIMIT %s", (status, limit))
            else:
                cur.execute("SELECT * FROM bookings ORDER BY created_at DESC LIMIT %s", (limit,))
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def get_booking(booking_id: int) -> "dict | None":
    conn = _connect()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM bookings WHERE id=%s", (booking_id,))
            row = cur.fetchone()
            return dict(row) if row else None
    finally:
        conn.close()


def mark_booking_feedback_sent(booking_id: int) -> None:
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE bookings SET feedback_sent_at = CURRENT_TIMESTAMP WHERE id = %s",
                (booking_id,),
            )
        conn.commit()
    finally:
        conn.close()


def list_bookings_due_for_feedback(days_after_checkout: int = 1) -> list:
    """Confirmed bookings whose checkout is >= N days ago and which have not had feedback requested yet."""
    conn = _connect()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT * FROM bookings
                WHERE status = 'confirmed'
                  AND feedback_sent_at IS NULL
                  AND check_out <= (CURRENT_DATE - (%s::int))
                ORDER BY check_out
            """, (days_after_checkout,))
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


# ── feedback tokens / submissions ─────────────────────────────────────────────

def create_feedback_token(token: str, booking_id: int) -> None:
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO feedback_tokens (token, booking_id) VALUES (%s, %s) "
                "ON CONFLICT (token) DO NOTHING",
                (token, booking_id),
            )
        conn.commit()
    finally:
        conn.close()


def get_feedback_token(token: str) -> "dict | None":
    conn = _connect()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM feedback_tokens WHERE token = %s", (token,))
            row = cur.fetchone()
            return dict(row) if row else None
    finally:
        conn.close()


def mark_feedback_token_used(token: str) -> None:
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE feedback_tokens SET used = TRUE, used_at = CURRENT_TIMESTAMP WHERE token = %s",
                (token,),
            )
        conn.commit()
    finally:
        conn.close()


def create_feedback(booking_id: int, booking_ref: str, guest_name: str,
                    rating: int, comment: str) -> int:
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO feedback (booking_id, booking_ref, guest_name, rating, comment)
                VALUES (%s, %s, %s, %s, %s) RETURNING id
            """, (booking_id, booking_ref, guest_name, rating, comment))
            return cur.fetchone()[0]
    finally:
        conn.commit()
        conn.close()


def add_feedback_media(feedback_id: int, filename: str, kind: str = "image") -> int:
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO feedback_media (feedback_id, filename, kind) VALUES (%s,%s,%s) RETURNING id",
                (feedback_id, filename, kind),
            )
            return cur.fetchone()[0]
    finally:
        conn.commit()
        conn.close()


def list_feedback(status: "str | None" = None, limit: int = 200) -> list:
    conn = _connect()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if status:
                cur.execute("SELECT * FROM feedback WHERE status = %s ORDER BY created_at DESC LIMIT %s", (status, limit))
            else:
                cur.execute("SELECT * FROM feedback ORDER BY created_at DESC LIMIT %s", (limit,))
            rows = [dict(r) for r in cur.fetchall()]
            if not rows:
                return rows
            ids = [r["id"] for r in rows]
            cur.execute("SELECT * FROM feedback_media WHERE feedback_id = ANY(%s) ORDER BY id", (ids,))
            media_by_fb: dict = {}
            for m in cur.fetchall():
                media_by_fb.setdefault(m["feedback_id"], []).append(dict(m))
            for r in rows:
                r["media"] = media_by_fb.get(r["id"], [])
            return rows
    finally:
        conn.close()


def list_approved_feedback(limit: int = 6) -> list:
    return list_feedback(status="approved", limit=limit)


def list_approved_feedback_media(limit: int = 20) -> list:
    conn = _connect()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT m.*, f.guest_name FROM feedback_media m
                  JOIN feedback f ON f.id = m.feedback_id
                WHERE m.approved = TRUE AND f.status = 'approved'
                ORDER BY m.id DESC LIMIT %s
            """, (limit,))
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def update_feedback_status(feedback_id: int, status: str) -> None:
    conn = _connect()
    try:
        with conn.cursor() as cur:
            if status == "approved":
                cur.execute(
                    "UPDATE feedback SET status=%s, approved_at=CURRENT_TIMESTAMP WHERE id=%s",
                    (status, feedback_id),
                )
            else:
                cur.execute("UPDATE feedback SET status=%s WHERE id=%s", (status, feedback_id))
        conn.commit()
    finally:
        conn.close()


def toggle_feedback_media_approval(media_id: int) -> bool:
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE feedback_media SET approved = NOT approved WHERE id = %s RETURNING approved", (media_id,))
            row = cur.fetchone()
        conn.commit()
        return bool(row[0]) if row else False
    finally:
        conn.close()


def delete_feedback_media(media_id: int) -> "str | None":
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM feedback_media WHERE id=%s RETURNING filename", (media_id,))
            row = cur.fetchone()
        conn.commit()
        return row[0] if row else None
    finally:
        conn.close()


def update_booking_status(booking_id: int, status: str, mark_acknowledged: bool = False) -> None:
    conn = _connect()
    try:
        with conn.cursor() as cur:
            if mark_acknowledged:
                cur.execute(
                    "UPDATE bookings SET status=%s, acknowledged_at=CURRENT_TIMESTAMP WHERE id=%s",
                    (status, booking_id),
                )
            else:
                cur.execute("UPDATE bookings SET status=%s WHERE id=%s", (status, booking_id))
        conn.commit()
    finally:
        conn.close()


def create_booking_token(token: str, phone: str, guest_name: str, email: str) -> None:
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO booking_tokens (token, phone, guest_name, email)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (token) DO UPDATE
                  SET phone = EXCLUDED.phone,
                      guest_name = EXCLUDED.guest_name,
                      email = EXCLUDED.email,
                      used = FALSE
                """,
                (token, phone, guest_name, email),
            )
        conn.commit()
    finally:
        conn.close()


def get_booking_token(token: str) -> "dict | None":
    conn = _connect()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM booking_tokens WHERE token = %s", (token,))
            row = cur.fetchone()
            return dict(row) if row else None
    finally:
        conn.close()


def mark_token_used(token: str) -> None:
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE booking_tokens SET used = TRUE WHERE token = %s", (token,))
        conn.commit()
    finally:
        conn.close()


def check_availability(check_in: str, check_out: str, room_type: str, rooms_requested: int = 1) -> bool:
    """Return True if rooms_requested of room_type are available for the date range."""
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT inventory FROM room_types WHERE name = %s", (room_type,))
            row = cur.fetchone()
            total_inventory = row[0] if row else 1
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
