"""
bot.py — Mondys Organic Farm WhatsApp Chatbot
Character: Mondy 🤖

Flow A — Explore the Farm  (info / FAQ)
Flow B — Book a Stay       (8-step guided booking)
"""
import re
import secrets
from datetime import date, timedelta
import whatsapp
import database
import pricing
import config


_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def _s(key: str, fallback: str = "") -> str:
    """Read a kv_settings value, falling back to a default if unset."""
    try:
        v = database.get_setting(key, "")
        return v if v else fallback
    except Exception:
        return fallback

# ═══════════════════════════════════════════════════════════════════════════════
# SESSION
# ═══════════════════════════════════════════════════════════════════════════════

SESSIONS: dict = {}


def _session(phone: str) -> dict:
    if phone not in SESSIONS:
        SESSIONS[phone] = {
            "state": "WELCOME",
            # guest profile
            "guest_name":        None,
            "email":             None,
            "adults":            None,
            "children":          None,
            # stay
            "check_in":          None,
            "check_out":         None,
            "nights":            None,
            "special_requests":  None,
            # room
            "room_type":         None,
            "room_count":        1,
            # food
            "food_preference":   None,
            "veg_count":         0,
            "nv_count":          0,
            "meal_plan_d1":      "No Meals",
            "meal_plan_sub":     "No Meals",
            # arrival
            "arrival_mode":      None,
            "pickup_point":      None,
            "vehicle_type":      None,
            # activities (dict: name → guest/unit count)
            "activities_d1":     {},
            "activities_d2":     {},
            "_pending_act":      None,   # temp while asking count
            "_pending_act_day":  None,   # "d1" or "d2"
            # internal
            "_totals":           None,
        }
    return SESSIONS[phone]


def _set(phone: str, key: str, value):
    SESSIONS[phone][key] = value


def _state(phone: str, state: str):
    SESSIONS[phone]["state"] = state


def _pax(phone: str) -> int:
    s = _session(phone)
    return (s["adults"] or 0) + (s["children"] or 0)


# ═══════════════════════════════════════════════════════════════════════════════
# DATE PARSING
# ═══════════════════════════════════════════════════════════════════════════════

_MONTHS = {
    "jan":1,"feb":2,"mar":3,"apr":4,"may":5,"jun":6,
    "jul":7,"aug":8,"sep":9,"oct":10,"nov":11,"dec":12,
    "january":1,"february":2,"march":3,"april":4,"june":6,
    "july":7,"august":8,"september":9,"october":10,"november":11,"december":12,
}


def _parse_date_range(text: str):
    """Returns (check_in, check_out, nights) or None."""
    text = text.lower().strip()
    yr   = date.today().year
    mp   = "|".join(sorted(_MONTHS.keys(), key=len, reverse=True))

    patterns = [
        # DD/MM/YYYY to DD/MM/YYYY  → groups: (d1,m1,y1, d2,m2,y2)
        (r"(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})\s*(?:to|[-–])\s*(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})",
         lambda m: (date(int(m[2]),int(m[1]),int(m[0])), date(int(m[5]),int(m[4]),int(m[3])))),
        # 4 June 2026 to 6 June 2026  → groups: (d1,mon1,y1, d2,mon2,y2)
        (rf"(\d{{1,2}})\w*\s+({mp})\s+(\d{{4}})\s*(?:to|[-–])\s*(\d{{1,2}})\w*\s+({mp})\s+(\d{{4}})",
         lambda m: (date(int(m[2]),_MONTHS[m[1]],int(m[0])), date(int(m[5]),_MONTHS[m[4]],int(m[3])))),
        # 4 June 2026 to 6 June (same year)  → groups: (d1,mon1,y1, d2,mon2)
        (rf"(\d{{1,2}})\w*\s+({mp})\s+(\d{{4}})\s*(?:to|[-–])\s*(\d{{1,2}})\w*\s+({mp})",
         lambda m: (date(int(m[2]),_MONTHS[m[1]],int(m[0])), date(int(m[2]),_MONTHS[m[4]],int(m[3])))),
        # 4 June to 6 June (current year)  → groups: (d1,mon1, d2,mon2)
        (rf"(\d{{1,2}})\w*\s+({mp})\s*(?:to|[-–])\s*(\d{{1,2}})\w*\s+({mp})",
         lambda m: (date(yr,_MONTHS[m[1]],int(m[0])), date(yr,_MONTHS[m[3]],int(m[2])))),
        # 4-6 June 2026  → groups: (d1,d2,mon,y)
        (rf"(\d{{1,2}})\w*\s*[-–]\s*(\d{{1,2}})\w*\s+({mp})\s+(\d{{4}})",
         lambda m: (date(int(m[3]),_MONTHS[m[2]],int(m[0])), date(int(m[3]),_MONTHS[m[2]],int(m[1])))),
        # 4-6 June (current year)  → groups: (d1,d2,mon)
        (rf"(\d{{1,2}})\w*\s*[-–]\s*(\d{{1,2}})\w*\s+({mp})",
         lambda m: (date(yr,_MONTHS[m[2]],int(m[0])), date(yr,_MONTHS[m[2]],int(m[1])))),
    ]
    for pat, fn in patterns:
        m = re.match(pat, text)
        if m:
            try:
                ci, co = fn(m.groups())
                if co <= ci:
                    co = co.replace(year=co.year + 1)
                return ci, co, (co - ci).days
            except Exception:
                continue
    return None


def _parse_single_date(text: str) -> "date | None":
    """Parse a single date like '6 June 2026' or '06/06/2026'."""
    text = text.lower().strip()
    yr   = date.today().year
    mp   = "|".join(sorted(_MONTHS.keys(), key=len, reverse=True))

    m = re.match(r"(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})", text)
    if m:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))

    m = re.match(rf"(\d{{1,2}})\w*\s+({mp})\s+(\d{{4}})", text)
    if m:
        return date(int(m.group(3)), _MONTHS[m.group(2)], int(m.group(1)))

    m = re.match(rf"(\d{{1,2}})\w*\s+({mp})", text)
    if m:
        return date(yr, _MONTHS[m.group(2)], int(m.group(1)))

    return None


def _parse_nights(text: str) -> "int | None":
    """Parse '2 nights' → 2."""
    m = re.search(r"(\d+)\s*nights?", text.lower())
    return int(m.group(1)) if m else None


# ═══════════════════════════════════════════════════════════════════════════════
# ── BACK NAVIGATION ───────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

_BACK_ROW  = {"id": "go_back", "title": "⬅ Go Back",    "description": "Return to previous step"}
_BACK_BTN  = {"id": "go_back", "title": "⬅ Back"}


def _show_path_buttons(phone: str):
    s = _session(phone)
    whatsapp.send_buttons(
        phone,
        f"What would you like to do, *{s.get('guest_name','there')}*?",
        [{"id": "path_explore", "title": "Explore the Farm"},
         {"id": "path_book",    "title": "Book a Stay"}],
    )
    _state(phone, "ASK_PATH")


def _show_email_prompt(phone: str):
    s = _session(phone)
    whatsapp.send_text(
        phone,
        f"Let's get your booking started, *{s['guest_name']}*! 🎉\n\n"
        "What's your *email address*? _(Type 'skip' to skip · 'back' to go back)_",
    )
    _state(phone, "ASK_EMAIL")


def _show_adults_prompt(phone: str):
    whatsapp.send_text(phone,
        "How many *adults* will be staying?\nEnter a number:\n_(Type 'back' to go back)_")
    _state(phone, "ASK_ADULTS")


def _show_children_prompt(phone: str):
    whatsapp.send_text(phone,
        "How many *children* will be coming?\n_(Enter 0 if none · 'back' to go back)_")
    _state(phone, "ASK_CHILDREN")


def _show_checkin_prompt(phone: str):
    whatsapp.send_text(
        phone,
        "What is your *check-in date*? 📅\n\n"
        "Examples:\n• _10 June 2026_\n• _10/06/2026_\n\n"
        "_(Or send a range: '10 June to 12 June' · 'back' to go back)_",
    )
    _state(phone, "ASK_CHECKIN")


def _show_special_requests_prompt(phone: str):
    s  = _session(phone)
    ci = date.fromisoformat(s["check_in"])
    co = date.fromisoformat(s["check_out"])
    whatsapp.send_text(
        phone,
        f"*{ci.strftime('%d %b')} → {co.strftime('%d %b %Y')}* "
        f"({s['nights']} night{'s' if s['nights']>1 else ''}) ✅\n\n"
        "Do you have any *special requests*?\n"
        "_(e.g. anniversary setup, early check-in — or type 'none' · 'back' to go back)_",
    )
    _state(phone, "ASK_SPECIAL_REQUESTS")


def _show_room_type_prompt(phone: str):
    whatsapp.send_buttons(
        phone,
        "Which room type would you like? 🏡\n\n"
        f"• *Family Suite* — Rs.{pricing.ROOM_RATES['Family Suite']:,}/night · up to 4 guests\n"
        f"• *Dormitory Stay* — Rs.{pricing.ROOM_RATES['Dormitory Stay']:,}/night · up to 6 guests",
        [
            {"id": "room_suite", "title": "Family Suite"},
            {"id": "room_dorm",  "title": "Dormitory Stay"},
            _BACK_BTN,
        ],
    )
    _state(phone, "ASK_ROOM_TYPE")


def _show_meals_sub_prompt(phone: str):
    pax = _pax(phone)
    whatsapp.send_list(
        phone,
        f"Which meals on *subsequent days* (Day 2+)? 🍽️\n_Per person · {pax} guests_",
        "Choose",
        [{"title": "Subsequent Days Plan", "rows": [
            {"id": "ms_bld","title": "All Meals (BLD)",  "description": f"Rs.{pricing.MEAL_COMBOS['All Meals (BLD)']:,}/pax"},
            {"id": "ms_bd", "title": "Breakfast+Dinner", "description": f"Rs.{pricing.MEAL_COMBOS['Breakfast+Dinner']:,}/pax"},
            {"id": "ms_ld", "title": "Lunch+Dinner",     "description": f"Rs.{pricing.MEAL_COMBOS['Lunch+Dinner']:,}/pax"},
            {"id": "ms_b",  "title": "Breakfast Only",   "description": f"Rs.{pricing.MEAL_COMBOS['Breakfast Only']:,}/pax"},
            {"id": "ms_d",  "title": "Dinner Only",      "description": f"Rs.{pricing.MEAL_COMBOS['Dinner Only']:,}/pax"},
            {"id": "ms_no", "title": "No Meals",         "description": "Self-arranged"},
            _BACK_ROW,
        ]}],
    )
    _state(phone, "ASK_MEALS_SUB")


def _back(phone: str):
    """Navigate to the previous step based on current state."""
    s     = _session(phone)
    state = s["state"]

    go = {
        "ASK_EMAIL":              _show_path_buttons,
        "ASK_ADULTS":             _show_email_prompt,
        "ASK_CHILDREN":           _show_adults_prompt,
        "ASK_CHECKIN":            _show_children_prompt,
        "ASK_CHECKOUT":           _show_checkin_prompt,
        "ASK_SPECIAL_REQUESTS":   _show_checkin_prompt,
        "ASK_ROOM_TYPE":          _show_special_requests_prompt,
        "ASK_ROOM_COUNT":         _show_room_type_prompt,
        "ASK_FOOD_PREF":          _ask_room_count_step,
        "ASK_VEG_COUNT":          _ask_food_pref_step,
        "ASK_MEALS_D1":           _ask_food_pref_step,
        "ASK_MEALS_SUB":          _ask_meals_d1,
        "ASK_TRANSPORT_NEEDED":   lambda p: (_ask_meals_d1(p) if s["nights"] <= 1 else _show_meals_sub_prompt(p)),
        "ASK_ARRIVAL_MODE":       _ask_arrival_step,
        "ASK_VEHICLE_TYPE":       _ask_pickup_point_step,
        "ASK_ACTIVITIES":         _ask_arrival_step,
        "ASK_ACTIVITY_COUNT":     _ask_activities_step,
        "SHOW_POLICY":            _ask_activities_step,
        "CONFIRM_BOOKING":        _show_policy,
    }

    fn = go.get(state)
    if fn:
        fn(phone)
    else:
        whatsapp.send_text(phone,
            "Can't go back further. Type *hi* to restart or *Menu* to browse info.")


# ═══════════════════════════════════════════════════════════════════════════════
# ── ENTRY ─────────────────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

def _welcome(phone: str):
    whatsapp.send_text(
        phone,
        f"🌾 *Welcome to {_s("property_name", config.PROPERTY_NAME)}!*\n\n"
        f"I'm *{config.BOT_NAME}* 🤖, your farm concierge.\n\n"
        "May I know your *name* to get started?",
    )
    _state(phone, "ASK_NAME")


def _ask_name(phone: str, content: str):
    # Stale button tap from a previous path-selection message
    if content in ("path_explore", "path_book"):
        _ask_path(phone, content)
        return

    name = content.strip().title()
    if len(name) < 2:
        whatsapp.send_text(phone, "Please share your name so I can assist you better 😊")
        return
    _set(phone, "guest_name", name)
    whatsapp.send_buttons(
        phone,
        f"Great to meet you, *{name}*! 🙏\n\nWhat would you like to do today?",
        [
            {"id": "path_explore", "title": "Explore the Farm"},
            {"id": "path_book",    "title": "Book a Stay"},
        ],
    )
    _state(phone, "ASK_PATH")


def _ask_path(phone: str, content: str):
    if content == "path_explore":
        _show_info_menu(phone)
    elif content == "path_book":
        _start_booking(phone)
    else:
        _welcome(phone)


# ═══════════════════════════════════════════════════════════════════════════════
# ── BOOKING FLOW ──────────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

def _start_booking(phone: str):
    s = _session(phone)
    whatsapp.send_text(
        phone,
        f"Let's get your booking started, *{s['guest_name']}*! 🎉\n\n"
        "What's your *email address*? We'll send your booking confirmation there.",
    )
    _state(phone, "ASK_EMAIL")


# ── Booking handoff: collect email, then send a link to the website ──────────

def _ask_email(phone: str, content: str):
    email = content.strip()
    if not _EMAIL_RE.match(email):
        whatsapp.send_text(
            phone,
            "Hmm, that doesn't look like an email. Try again — e.g. _you@example.com_",
        )
        return
    _set(phone, "email", email)

    s = _session(phone)
    token = secrets.token_urlsafe(16)
    database.create_booking_token(
        token=token,
        phone=phone,
        guest_name=s["guest_name"],
        email=email,
    )
    url = f"{config.BASE_URL.rstrip('/')}/book/{token}"

    whatsapp.send_text(
        phone,
        f"All set, *{s['guest_name']}* ✨\n\n"
        f"Continue your booking on our website 👇\n"
        f"{url}\n\n"
        f"You'll pick your dates, room, meals & activities — then send us the request. "
        f"We'll confirm availability and payment shortly after.\n\n"
        f"_The link is unique to you — don't share it._\n\n"
        f"Type *Hi* anytime to start over, or *Menu* to browse the farm.",
    )
    _state(phone, "BOOKING_LINK_SENT")


def _ask_adults(phone: str, content: str):
    if not content.strip().isdigit() or int(content) < 1:
        whatsapp.send_text(phone, "Please enter a valid number of adults (e.g. 2).")
        return
    _set(phone, "adults", int(content.strip()))
    whatsapp.send_text(phone, "How many *children* will be coming?\n_(Enter 0 if none)_")
    _state(phone, "ASK_CHILDREN")


def _ask_children(phone: str, content: str):
    if not content.strip().isdigit():
        whatsapp.send_text(phone, "Please enter 0 or a valid number of children.")
        return
    _set(phone, "children", int(content.strip()))
    whatsapp.send_text(
        phone,
        "What is your *check-in date*? 📅\n\n"
        "Examples:\n"
        "• _10 June 2026_\n"
        "• _10/06/2026_",
    )
    _state(phone, "ASK_CHECKIN")


# ── Step 2: Stay Dates ────────────────────────────────────────────────────────

def _ask_checkin(phone: str, content: str):
    # Try as full range first
    result = _parse_date_range(content)
    if result:
        ci, co, nights = result
        if nights <= 0:
            whatsapp.send_text(phone, "Check-out must be after check-in. Please try again.")
            return
        if ci < date.today():
            whatsapp.send_text(phone, "Check-in cannot be in the past. Please try again.")
            return
        _set(phone, "check_in",  ci.isoformat())
        _set(phone, "check_out", co.isoformat())
        _set(phone, "nights",    nights)
        _ask_special_requests(phone)
        return

    # Single date
    ci = _parse_single_date(content)
    if not ci:
        whatsapp.send_text(phone, "Sorry, I couldn't read that date.\nExample: _10 June 2026_")
        return
    if ci < date.today():
        whatsapp.send_text(phone, "Check-in cannot be in the past. Please try again.")
        return
    _set(phone, "check_in", ci.isoformat())
    whatsapp.send_text(
        phone,
        f"Check-in: *{ci.strftime('%d %b %Y')}* ✅\n\n"
        "What is your *check-out date*?\n"
        "_(Or type e.g. '2 nights')_",
    )
    _state(phone, "ASK_CHECKOUT")


def _ask_checkout(phone: str, content: str):
    s  = _session(phone)
    ci = date.fromisoformat(s["check_in"])

    # "N nights"
    nights = _parse_nights(content)
    if nights and nights > 0:
        co = ci + timedelta(days=nights)
        _set(phone, "check_out", co.isoformat())
        _set(phone, "nights",    nights)
        _ask_special_requests(phone)
        return

    # Single date
    co = _parse_single_date(content)
    if not co:
        whatsapp.send_text(phone, "Sorry, I couldn't read that date.\nExample: _12 June 2026_ or _2 nights_")
        return
    if co <= ci:
        whatsapp.send_text(phone, "Check-out must be after check-in. Please try again.")
        return
    nights = (co - ci).days
    _set(phone, "check_out", co.isoformat())
    _set(phone, "nights",    nights)
    _ask_special_requests(phone)


def _ask_special_requests(phone: str):
    s = _session(phone)
    ci = date.fromisoformat(s["check_in"])
    co = date.fromisoformat(s["check_out"])
    whatsapp.send_text(
        phone,
        f"*{ci.strftime('%d %b')} → {co.strftime('%d %b %Y')}* "
        f"({s['nights']} night{'s' if s['nights'] > 1 else ''}) ✅\n\n"
        "Check-in: *{ci}* | Check-out: *{co}*\n\n"
        "Do you have any *special requests*?\n"
        "_(e.g. anniversary setup, early check-in, dietary needs — or type 'none')_".format(ci=_s("check_in_time", config.CHECK_IN_TIME), co=_s("check_out_time", config.CHECK_OUT_TIME)),
    )
    _state(phone, "ASK_SPECIAL_REQUESTS")


def _ask_special_requests_input(phone: str, content: str):
    req = None if content.lower().strip() == "none" else content.strip()
    _set(phone, "special_requests", req)

    # ── Step 3: Room Type ─────────────────────────────────────────────────────
    whatsapp.send_buttons(
        phone,
        "Which room type would you like? 🏡\n\n"
        f"• *Family Suite* — Rs.{pricing.ROOM_RATES['Family Suite']:,}/night · up to 4 guests\n"
        f"• *Dormitory Stay* — Rs.{pricing.ROOM_RATES['Dormitory Stay']:,}/night · up to 6 guests",
        [
            {"id": "room_suite", "title": "Family Suite"},
            {"id": "room_dorm",  "title": "Dormitory Stay"},
        ],
    )
    _state(phone, "ASK_ROOM_TYPE")


def _ask_room_type(phone: str, content: str):
    room_map = {"room_suite": "Family Suite", "room_dorm": "Dormitory Stay"}
    room = room_map.get(content)
    if not room:
        whatsapp.send_text(phone, "Please tap one of the room options above.")
        return

    _set(phone, "room_type", room)
    _ask_room_count_step(phone)


def _ask_room_count_step(phone: str):
    s         = _session(phone)
    room      = s["room_type"]
    pax       = _pax(phone)
    limit     = pricing.ROOM_PAX_LIMIT.get(room, 6)
    inventory = pricing.ROOM_INVENTORY.get(room, 1)

    # Minimum rooms needed to fit the group
    import math
    min_rooms = math.ceil(pax / limit)

    if min_rooms > inventory:
        whatsapp.send_text(
            phone,
            f"😔 Sorry, we only have *{inventory} {room}(s)* which can accommodate "
            f"up to *{inventory * limit} guests*. Your group has *{pax}*.\n\n"
            "Please try the other room type or contact us for large groups.",
        )
        # Show room type selector again
        whatsapp.send_buttons(
            phone,
            "Choose a room type:",
            [
                {"id": "room_suite", "title": "Family Suite"},
                {"id": "room_dorm",  "title": "Dormitory Stay"},
            ],
        )
        _state(phone, "ASK_ROOM_TYPE")
        return

    rows = []
    for n in range(1, inventory + 1):
        capacity = n * limit
        suffix   = "s" if n > 1 else ""
        note     = " ← minimum for your group" if n == min_rooms and min_rooms > 1 else ""
        rows.append({
            "id":          f"rc_{n}",
            "title":       f"{n} Room{suffix}",
            "description": f"Up to {capacity} guests{note}",
        })

    whatsapp.send_list(
        phone,
        f"How many *{room}s* would you like to book?\n"
        f"_(Your group: {pax} guests · {limit} guests/room)_",
        "Select",
        [{"title": f"{room} — Count", "rows": rows}],
    )
    _state(phone, "ASK_ROOM_COUNT")


def _ask_room_count(phone: str, content: str):
    if not content.startswith("rc_") or not content[3:].isdigit():
        whatsapp.send_text(phone, "Please select from the list.")
        return

    count = int(content[3:])
    s     = _session(phone)
    room  = s["room_type"]
    pax   = _pax(phone)
    limit = pricing.ROOM_PAX_LIMIT.get(room, 6)

    if count * limit < pax:
        whatsapp.send_text(
            phone,
            f"*{count} room(s)* can accommodate up to *{count * limit} guests*, "
            f"but your group has *{pax}*. Please select more rooms.",
        )
        _ask_room_count_step(phone)
        return

    _set(phone, "room_count", count)

    # Check availability
    if not database.check_availability(s["check_in"], s["check_out"], room, count):
        avail = _rooms_available(s["check_in"], s["check_out"], room)
        if avail == 0:
            msg = f"😔 *{room}* is fully booked for those dates."
        else:
            msg = f"😔 Only *{avail} {room}(s)* available for those dates (you requested {count})."
        whatsapp.send_buttons(
            phone,
            msg + "\n\nWhat would you like to do?",
            [
                {"id": "retry_dates", "title": "Different Dates"},
                {"id": "retry_room",  "title": "Other Room Type"},
            ],
        )
        _state(phone, "ROOM_UNAVAILABLE")
        return

    _proceed_to_food(phone)


def _rooms_available(check_in: str, check_out: str, room_type: str) -> int:
    """How many rooms of this type are still free for the dates."""
    from pricing import ROOM_INVENTORY
    import psycopg2
    total = ROOM_INVENTORY.get(room_type, 1)
    try:
        conn = database._connect()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COALESCE(SUM(room_count), 0) FROM bookings
                WHERE status != 'cancelled' AND room_type = %s
                  AND check_in < %s AND check_out > %s
            """, (room_type, check_out, check_in))
            booked = cur.fetchone()[0]
        conn.close()
        return max(0, total - booked)
    except Exception:
        return 0


def _proceed_to_food(phone: str):
    s    = _session(phone)
    room = s["room_type"]
    rc   = s["room_count"]
    label = f"{rc}× {room}" if rc > 1 else room
    # ── Step 4: Meal Planning ─────────────────────────────────────────────────
    whatsapp.send_list(
        phone,
        f"*{label}* — available ✅\n\n"
        "What are your *food preferences*?",
        "Select",
        [{"title": "Dietary Preference", "rows": [
            {"id": "food_veg",    "title": "Vegetarian",    "description": "All Veg meals"},
            {"id": "food_nv",     "title": "Non-Vegetarian","description": "Includes meat, fish, eggs"},
            {"id": "food_mixed",  "title": "Mixed Group",   "description": "Some Veg, some Non-Veg"},
        ]}],
    )
    _state(phone, "ASK_FOOD_PREF")


def _room_unavailable(phone: str, content: str):
    if content == "retry_dates":
        whatsapp.send_text(phone, "Please share new check-in & check-out dates:")
        _state(phone, "ASK_CHECKIN")
    elif content == "retry_room":
        s     = _session(phone)
        other = "Dormitory Stay" if s.get("room_type") == "Family Suite" else "Family Suite"
        _set(phone, "room_type", other)
        _ask_room_count_step(phone)
    else:
        whatsapp.send_text(phone, "Please tap one of the options.")


def _ask_food_pref_step(phone: str):
    whatsapp.send_list(
        phone, "What are your *food preferences*?", "Select",
        [{"title": "Dietary Preference", "rows": [
            {"id": "food_veg",   "title": "Vegetarian",     "description": "All Veg meals"},
            {"id": "food_nv",    "title": "Non-Vegetarian", "description": "Includes meat, fish, eggs"},
            {"id": "food_mixed", "title": "Mixed Group",    "description": "Some Veg, some Non-Veg"},
        ]}],
    )
    _state(phone, "ASK_FOOD_PREF")


_FOOD_MAP = {"food_veg": "Vegetarian", "food_nv": "Non-Vegetarian", "food_mixed": "Mixed"}


def _ask_food_pref(phone: str, content: str):
    pref = _FOOD_MAP.get(content)
    if not pref:
        whatsapp.send_text(phone, "Please select from the list above.")
        return
    _set(phone, "food_preference", pref)
    pax = _pax(phone)

    if pref == "Mixed":
        whatsapp.send_text(
            phone,
            f"Your group has *{pax} guests*. 🥗\n\n"
            "How many are *Vegetarian*?\n_(Non-Veg count will be calculated automatically)_\n"
            "Enter a number:",
        )
        _state(phone, "ASK_VEG_COUNT")
    else:
        # all veg or all nv
        _set(phone, "veg_count", pax if pref == "Vegetarian" else 0)
        _set(phone, "nv_count",  0   if pref == "Vegetarian" else pax)
        _ask_meals_d1(phone)


def _ask_veg_count(phone: str, content: str):
    pax = _pax(phone)
    if not content.strip().isdigit() or not (0 <= int(content.strip()) <= pax):
        whatsapp.send_text(phone, f"Please enter a number between 0 and {pax}.")
        return
    veg = int(content.strip())
    _set(phone, "veg_count", veg)
    _set(phone, "nv_count",  pax - veg)
    _ask_meals_d1(phone)


_MEAL_ID_MAP = {
    "m1_bld": "All Meals (BLD)", "m1_bd": "Breakfast+Dinner",
    "m1_ld":  "Lunch+Dinner",    "m1_b":  "Breakfast Only",
    "m1_d":   "Dinner Only",     "m1_no": "No Meals",
    "ms_bld": "All Meals (BLD)", "ms_bd": "Breakfast+Dinner",
    "ms_ld":  "Lunch+Dinner",    "ms_b":  "Breakfast Only",
    "ms_d":   "Dinner Only",     "ms_no": "No Meals",
}


def _ask_meals_d1(phone: str):
    pax = _pax(phone)
    whatsapp.send_list(
        phone,
        f"Which meals on *Day 1* (arrival day)? 🍽️\n_Per person · {pax} guests_",
        "Choose",
        [{"title": "Day 1 Meal Plan", "rows": [
            {"id": "m1_bld","title": "All Meals (BLD)",  "description": f"Rs.{pricing.MEAL_COMBOS['All Meals (BLD)']:,}/pax"},
            {"id": "m1_bd", "title": "Breakfast+Dinner", "description": f"Rs.{pricing.MEAL_COMBOS['Breakfast+Dinner']:,}/pax"},
            {"id": "m1_ld", "title": "Lunch+Dinner",     "description": f"Rs.{pricing.MEAL_COMBOS['Lunch+Dinner']:,}/pax"},
            {"id": "m1_b",  "title": "Breakfast Only",   "description": f"Rs.{pricing.MEAL_COMBOS['Breakfast Only']:,}/pax"},
            {"id": "m1_d",  "title": "Dinner Only",      "description": f"Rs.{pricing.MEAL_COMBOS['Dinner Only']:,}/pax"},
            {"id": "m1_no", "title": "No Meals",         "description": "Self-arranged"},
        ]}],
    )
    _state(phone, "ASK_MEALS_D1")


def _ask_meals_d1_input(phone: str, content: str):
    plan = _MEAL_ID_MAP.get(content)
    if not plan:
        whatsapp.send_text(phone, "Please select a meal plan from the list.")
        return
    _set(phone, "meal_plan_d1", plan)

    s = _session(phone)
    if s["nights"] > 1:
        pax = _pax(phone)
        whatsapp.send_list(
            phone,
            f"Which meals on *subsequent days* (Day 2 onwards)? 🍽️\n_Per person · {pax} guests_",
            "Choose",
            [{"title": "Subsequent Days Plan", "rows": [
                {"id": "ms_bld","title": "All Meals (BLD)",  "description": f"Rs.{pricing.MEAL_COMBOS['All Meals (BLD)']:,}/pax"},
                {"id": "ms_bd", "title": "Breakfast+Dinner", "description": f"Rs.{pricing.MEAL_COMBOS['Breakfast+Dinner']:,}/pax"},
                {"id": "ms_ld", "title": "Lunch+Dinner",     "description": f"Rs.{pricing.MEAL_COMBOS['Lunch+Dinner']:,}/pax"},
                {"id": "ms_b",  "title": "Breakfast Only",   "description": f"Rs.{pricing.MEAL_COMBOS['Breakfast Only']:,}/pax"},
                {"id": "ms_d",  "title": "Dinner Only",      "description": f"Rs.{pricing.MEAL_COMBOS['Dinner Only']:,}/pax"},
                {"id": "ms_no", "title": "No Meals",         "description": "Self-arranged"},
            ]}],
        )
        _state(phone, "ASK_MEALS_SUB")
    else:
        _set(phone, "meal_plan_sub", "No Meals")
        _ask_arrival_step(phone)


def _ask_meals_sub(phone: str, content: str):
    plan = _MEAL_ID_MAP.get(content)
    if not plan:
        whatsapp.send_text(phone, "Please select a meal plan from the list.")
        return
    _set(phone, "meal_plan_sub", plan)
    _ask_arrival_step(phone)


# ── Step 5: Arrival ───────────────────────────────────────────────────────────

def _ask_arrival_step(phone: str):
    """Ask if the guest needs pickup transport (Yes / No)."""
    whatsapp.send_buttons(
        phone,
        "Do you need *transport* to the farm? 🚗\n\n"
        "_(Pickup available from railway stations & airports)_",
        [
            {"id": "transport_yes", "title": "Yes, Need Pickup"},
            {"id": "transport_no",  "title": "No, Self-Drive"},
            _BACK_BTN,
        ],
    )
    _state(phone, "ASK_TRANSPORT_NEEDED")


def _ask_transport_needed(phone: str, content: str):
    if content == "go_back":
        _back(phone)
        return
    if content == "transport_no":
        _set(phone, "arrival_mode",  "Self-Drive")
        _set(phone, "pickup_point",  None)
        _set(phone, "vehicle_type",  None)
        _ask_activities_step(phone)
    elif content == "transport_yes":
        _ask_pickup_point_step(phone)
    else:
        whatsapp.send_text(phone, "Please tap *Yes, Need Pickup* or *No, Self-Drive*.")


def _ask_pickup_point_step(phone: str):
    """Show the list of pickup points."""
    whatsapp.send_list(
        phone,
        "Where will you be arriving from? 📍\nWe'll arrange pickup from there.",
        "Select Point",
        [{"title": "Pickup Points", "rows": [
            {"id": "arr_kudal",  "title": "Kudal Railway",      "description": f"Rs.{pricing.PICKUP_POINTS['Kudal Railway Station']:,} base"},
            {"id": "arr_sawant", "title": "Sawantwadi Railway", "description": f"Rs.{pricing.PICKUP_POINTS['Sawantwadi Railway Station']:,} base"},
            {"id": "arr_mopa",   "title": "Mopa Airport",       "description": f"Rs.{pricing.PICKUP_POINTS['Mopa Airport']:,} base"},
            {"id": "arr_chipi",  "title": "Chipi Airport",      "description": f"Rs.{pricing.PICKUP_POINTS['Chipi Airport']:,} base"},
            _BACK_ROW,
        ]}],
    )
    _state(phone, "ASK_ARRIVAL_MODE")


_ARRIVAL_MAP = {
    "arr_kudal":  ("Railway", "Kudal Railway Station"),
    "arr_sawant": ("Railway", "Sawantwadi Railway Station"),
    "arr_mopa":   ("Flight",  "Mopa Airport"),
    "arr_chipi":  ("Flight",  "Chipi Airport"),
}


def _ask_vehicle_type_step(phone: str):
    pax = _pax(phone)
    whatsapp.send_list(
        phone,
        f"What type of *vehicle* for pickup?\n_{pax} guests to transport_",
        "Select Vehicle",
        [{"title": "Vehicle Type", "rows": [
            {"id": "veh_sedan", "title": "Sedan",       "description": "4-seater car"},
            {"id": "veh_muv",   "title": "MUV",         "description": "6-7 seater MUV"},
            {"id": "veh_bus",   "title": "Charter Bus", "description": "Large group (20+ pax)"},
            _BACK_ROW,
        ]}],
    )
    _state(phone, "ASK_VEHICLE_TYPE")


def _ask_arrival_mode(phone: str, content: str):
    if content == "go_back":
        _back(phone)
        return
    result = _ARRIVAL_MAP.get(content)
    if not result:
        whatsapp.send_text(phone, "Please select a pickup point from the list.")
        return
    mode, pickup = result
    _set(phone, "arrival_mode", mode)
    _set(phone, "pickup_point", pickup)
    _ask_vehicle_type_step(phone)


def _ask_vehicle_type(phone: str, content: str):
    if content == "go_back":
        _back(phone)
        return
    veh_map = {"veh_sedan": "Sedan", "veh_muv": "MUV", "veh_bus": "Charter Bus"}
    veh = veh_map.get(content)
    if not veh:
        whatsapp.send_text(phone, "Please select a vehicle type from the list.")
        return
    _set(phone, "vehicle_type", veh)
    _ask_activities_step(phone)


# ── Step 6: Activities ────────────────────────────────────────────────────────
# Activities stored as {name: count} in activities_d1 (farm) and activities_d2 (outdoor).
# Both are shown in one combined list. Outdoor section only shown if nights >= 2.

_D1_MAP = {
    "d1_petting": "Animal Petting",
    "d1_bullock": "Bullock Cart Ride",
    "d1_bkfast":  "Pick Your Breakfast Plate",
    "d1_trek":    "Trekking",
    "d1_swim":    "Swimming Pool",
    "d1_rain":    "Gazebo Rain Dance",
    "d1_games":   "Indoor Games",
}

_D2_MAP = {
    "d2_kayak":    "Kayaking",
    "d2_beach":    "Beach & Temple Visit",
    "d2_malvan":   "Malvan Water Sports",
    "d2_vengurla": "Vengurla Beach Exploration",
}


def _act_label(acts: dict) -> str:
    if not acts:
        return "None selected"
    parts = []
    for name, cnt in acts.items():
        info = pricing.ACTIVITIES_D1.get(name) or pricing.ACTIVITIES_D2.get(name, {})
        if info.get("free") or info.get("per") == "group":
            parts.append(name)
        else:
            unit = "boat" if info.get("per") == "boat" else "guest"
            parts.append(f"{name} ({cnt} {unit}{'s' if cnt>1 else ''})")
    return ", ".join(parts)


def _ask_activities_step(phone: str):
    """Show all activities in one combined list. Outdoor section only for nights ≥ 2."""
    s   = _session(phone)
    pax = _pax(phone)

    all_sel = {**s["activities_d1"], **s["activities_d2"]}
    sel     = _act_label(all_sel)

    sections = [
        {"title": "🌿 Farm Activities", "rows": [
            {"id": "d1_petting", "title": "Animal Petting",       "description": "Free · all guests · 1 hr"},
            {"id": "d1_bullock", "title": "Bullock Cart Ride",    "description": "Rs.100/guest · 15 mins"},
            {"id": "d1_bkfast",  "title": "Pick Breakfast Plate", "description": "Rs.300/guest · 30 mins"},
            {"id": "d1_trek",    "title": "Trekking",             "description": "Free · all guests · 2 hrs"},
            {"id": "d1_swim",    "title": "Swimming Pool",        "description": "Free · all guests · all day"},
            {"id": "d1_rain",    "title": "Gazebo Rain Dance",    "description": "Rs.150/guest · 2 hrs"},
            {"id": "d1_games",   "title": "Indoor Games",         "description": "Rs.150/guest · 3-4 hrs"},
        ]},
        {"title": "🌊 Outdoor Adventures", "rows": [
            {"id": "d2_kayak",    "title": "Kayaking",            "description": "Rs.400/boat · 1 hour"},
            {"id": "d2_beach",    "title": "Beach & Temple Visit","description": "Free · transport extra"},
            {"id": "d2_malvan",   "title": "Malvan Water Sports", "description": "Free · local fare applies"},
            {"id": "d2_vengurla", "title": "Vengurla Beach",      "description": "Free · transport extra"},
        ]},
    ]

    whatsapp.send_list(
        phone,
        f"*Activities* 🎯\nSelected: *{sel}*\n\nTap to add:",
        "Select",
        sections,
    )
    whatsapp.send_buttons(
        phone,
        "Tap *Done* when you've selected all activities:",
        [
            {"id": "act_done", "title": "✅ Done"},
            _BACK_BTN,
        ],
    )
    _state(phone, "ASK_ACTIVITIES")


def _ask_activities(phone: str, content: str):
    if content == "go_back":
        _back(phone)
        return
    if content in ("act_done", "d1_done", "d2_done"):
        # act_done = current button; d1/d2_done = stale taps from old flow
        _show_policy(phone)
        return

    pax = _pax(phone)

    # Farm activity?
    act = _D1_MAP.get(content)
    if act:
        info = pricing.ACTIVITIES_D1.get(act, {})
        if info.get("free") or info.get("per") == "group":
            _session(phone)["activities_d1"][act] = pax
            _ask_activities_step(phone)
        else:
            _set(phone, "_pending_act",     act)
            _set(phone, "_pending_act_day", "d1")
            unit = "boats" if info.get("per") == "boat" else "guests"
            whatsapp.send_text(
                phone,
                f"*{act}* — Rs.{info['price']:,}/{info['per']}\n\n"
                f"How many *{unit}* will do this? _(1–{pax} · type 'back' to cancel)_",
            )
            _state(phone, "ASK_ACTIVITY_COUNT")
        return

    # Outdoor activity?
    act = _D2_MAP.get(content)
    if act:
        info = pricing.ACTIVITIES_D2.get(act, {})
        if info.get("free") or info.get("per") == "group":
            _session(phone)["activities_d2"][act] = pax
            _ask_activities_step(phone)
        else:
            _set(phone, "_pending_act",     act)
            _set(phone, "_pending_act_day", "d2")
            unit = "boats" if info.get("per") == "boat" else "guests"
            whatsapp.send_text(
                phone,
                f"*{act}* — Rs.{info['price']:,}/{info['per']}\n\n"
                f"How many *{unit}*? _(1–{pax} · type 'back' to cancel)_",
            )
            _state(phone, "ASK_ACTIVITY_COUNT")
        return

    whatsapp.send_text(phone, "Please select an activity from the list, or tap *Done* to continue.")


def _ask_activity_count(phone: str, content: str):
    """Guest/boat count for a paid activity."""
    s   = _session(phone)
    pax = _pax(phone)
    day = s.get("_pending_act_day", "d1")   # read BEFORE clearing

    # Stale Done taps — cancel pending, proceed
    if content in ("act_done", "d1_done", "d2_done"):
        _set(phone, "_pending_act",     None)
        _set(phone, "_pending_act_day", None)
        _show_policy(phone)
        return

    if content.lower().strip() == "back":
        _set(phone, "_pending_act",     None)
        _set(phone, "_pending_act_day", None)
        _ask_activities_step(phone)
        return

    if not content.strip().isdigit() or not (1 <= int(content.strip()) <= pax):
        whatsapp.send_text(phone, f"Please enter a number between 1 and {pax}.")
        return

    count = int(content.strip())
    act   = s["_pending_act"]
    _set(phone, "_pending_act",     None)
    _set(phone, "_pending_act_day", None)

    if day == "d1":
        s["activities_d1"][act] = count
    else:
        s["activities_d2"][act] = count
    _ask_activities_step(phone)   # re-show combined list + Done


# ── Step 7: Policy ────────────────────────────────────────────────────────────

def _show_policy(phone: str):
    whatsapp.send_buttons(
        phone,
        f"📜 *Booking Policy — Please Read*\n\n"
        f"{_s("cancellation_policy", config.CANCELLATION_POLICY)}\n\n"
        f"{config.PAYMENT_INFO}\n\n"
        "Tap *Got It* to see your full booking summary.",
        [
            {"id": "policy_ok",   "title": "Got It, Continue"},
            {"id": "policy_call", "title": "Talk to Team"},
        ],
    )
    _state(phone, "SHOW_POLICY")


def _handle_policy(phone: str, content: str):
    if content == "policy_call":
        _send_contact_info(phone)
        return
    _show_summary(phone)


# ── Step 8: Summary & Confirm ─────────────────────────────────────────────────

def _show_summary(phone: str):
    s   = _session(phone)
    pax = _pax(phone)

    totals = pricing.calculate_total(
        room_type     = s["room_type"],
        nights        = s["nights"],
        pax           = pax,
        meal_plan_d1  = s["meal_plan_d1"],
        meal_plan_sub = s["meal_plan_sub"],
        activities_d1 = s["activities_d1"],
        activities_d2 = s["activities_d2"],
        pickup_point  = s["pickup_point"],
        vehicle_type  = s["vehicle_type"],
        room_count    = s.get("room_count", 1),
    )
    SESSIONS[phone]["_totals"] = totals

    advance = round(totals["total"] * config.ADVANCE_PERCENT / 100)

    d1_acts = _act_label(s["activities_d1"])
    d2_acts = _act_label(s["activities_d2"]) if s["activities_d2"] else "None"
    meals   = f"Day 1: {s['meal_plan_d1']}"
    if s["nights"] > 1:
        meals += f" | Day 2+: {s['meal_plan_sub']}"
    transport_line = (
        f"{s['pickup_point']} ({s['vehicle_type']}): Rs.{totals['transport']:,}"
        if s["pickup_point"] else "Self-drive / Self-arranged"
    )

    ci = date.fromisoformat(s["check_in"])
    co = date.fromisoformat(s["check_out"])

    summary = (
        f"📋 *Booking Summary — {_s("property_name", config.PROPERTY_NAME)}*\n\n"
        f"*Name:*    {s['guest_name']}\n"
        f"*Guests:*  {s['adults']} adult(s), {s['children']} child(ren)\n"
        f"*Email:*   {s.get('email') or 'Not provided'}\n\n"
        f"*Check-in:*  {ci.strftime('%d %b %Y')}  {_s("check_in_time", config.CHECK_IN_TIME)}\n"
        f"*Check-out:* {co.strftime('%d %b %Y')}  {_s("check_out_time", config.CHECK_OUT_TIME)}\n"
        f"*Nights:*    {s['nights']}\n\n"
        f"*Room:*     {s.get('room_count',1)}× {s['room_type']}\n"
        f"*Food:*     {s['food_preference']} "
        f"({s['veg_count']} Veg / {s['nv_count']} Non-Veg)\n"
        f"*Meals:*    {meals}\n\n"
        f"*Farm Activities:*    {d1_acts}\n"
        f"*Outdoor Activities:* {d2_acts}\n\n"
        f"*Arrival:*  {transport_line}\n\n"
        f"*Special Requests:* {s.get('special_requests') or 'None'}\n\n"
        f"{'—'*22}\n"
        f"  Room:        Rs.{totals['room']:,}\n"
        f"  Meals:       Rs.{totals['meals']:,}\n"
        f"  Activities:  Rs.{totals['activities']:,}\n"
        f"  Transport:   Rs.{totals['transport']:,}\n"
        f"{'—'*22}\n"
        f"  *TOTAL:      Rs.{totals['total']:,}*\n"
        f"  Advance due: Rs.{advance:,} ({config.ADVANCE_PERCENT}%)\n"
        f"{'—'*22}\n\n"
        "Please review and confirm."
    )

    whatsapp.send_buttons(
        phone, summary,
        [
            {"id": "confirm_yes",  "title": "Confirm Booking"},
            {"id": "confirm_edit", "title": "Change Dates"},
            {"id": "confirm_call", "title": "Talk to Team"},
        ],
    )
    _state(phone, "CONFIRM_BOOKING")


def _confirm_booking(phone: str, content: str):
    if content == "confirm_call":
        _send_contact_info(phone)
        return
    if content == "confirm_edit":
        whatsapp.send_text(phone, "Please share your new check-in and check-out dates:")
        _state(phone, "ASK_CHECKIN")
        return
    if content != "confirm_yes":
        whatsapp.send_text(phone, "Please tap Confirm, Change Dates, or Talk to Team.")
        return

    s      = _session(phone)
    totals = s.get("_totals") or {}
    pax    = _pax(phone)
    advance = round(totals.get("total", 0) * config.ADVANCE_PERCENT / 100)

    booking_id, ref = database.create_booking(
        phone            = phone,
        guest_name       = s["guest_name"],
        email            = s.get("email"),
        adults           = s["adults"],
        children         = s["children"],
        check_in         = s["check_in"],
        check_out        = s["check_out"],
        nights           = s["nights"],
        special_requests = s.get("special_requests"),
        room_type        = s["room_type"],
        room_count       = s.get("room_count", 1),
        food_preference  = s["food_preference"],
        veg_count        = s["veg_count"],
        nv_count         = s["nv_count"],
        meal_plan_d1     = s["meal_plan_d1"],
        meal_plan_sub    = s["meal_plan_sub"],
        arrival_mode     = s.get("arrival_mode"),
        pickup_point     = s.get("pickup_point"),
        vehicle_type     = s.get("vehicle_type"),
        activities_d1    = s["activities_d1"],
        activities_d2    = s["activities_d2"],
        total_amount     = totals.get("total", 0),
        advance_amount   = advance,
    )

    ci = date.fromisoformat(s["check_in"])

    # 1. Confirmation
    whatsapp.send_text(
        phone,
        f"🎉 *Booking Confirmed!*\n\n"
        f"*Booking Ref:* {ref}\n"
        f"*Name:* {s['guest_name']}\n"
        f"*Dates:* {s['check_in']} → {s['check_out']}\n"
        f"*Room:* {s.get('room_count',1)}× {s['room_type']}\n"
        f"*Total:* Rs.{totals.get('total',0):,}\n\n"
        f"{config.PAYMENT_INFO}\n\n"
        f"*Please pay the advance of Rs.{advance:,} to confirm your slot.*",
    )

    # 2. Arrival info
    whatsapp.send_text(
        phone,
        f"📍 *Farm Details*\n\n"
        f"*Address:* {_s("property_address", config.PROPERTY_ADDRESS)}\n"
        f"*GPS:* {_s("property_gps", config.PROPERTY_GPS)}\n\n"
        f"*Check-in:*  {_s("check_in_time", config.CHECK_IN_TIME)}\n"
        f"*Check-out:* {_s("check_out_time", config.CHECK_OUT_TIME)}\n\n"
        f"*Contact:* {_s("property_contact", config.PROPERTY_CONTACT)}\n"
        f"*Email:* {_s("support_email", config.SUPPORT_EMAIL)}\n\n"
        "_Please carry a valid Govt. Photo ID._",
    )

    # 3. Medical
    whatsapp.send_text(
        phone,
        f"🏥 *Medical & Emergency*\n\n"
        f"Nearest Hospital: {_s("nearest_hospital", config.NEAREST_HOSPITAL)}\n"
        f"Contact: {_s("medical_contact", config.MEDICAL_CONTACT)}\n"
        f"Ambulance: {_s("ambulance", config.AMBULANCE)}\n"
        f"{_s("pharmacy_info", config.PHARMACY_INFO)}",
    )

    # 5. Farewell
    whatsapp.send_text(
        phone,
        f"🌾 *Thank you for choosing {_s("property_name", config.PROPERTY_NAME)}!*\n\n"
        f"Your booking reference is *{ref}*. "
        "Our team will reach out to confirm your advance payment.\n\n"
        f"See you soon! 🙏\n\n"
        "Type *Hi* anytime to make another booking.",
    )

    del SESSIONS[phone]


def _send_contact_info(phone: str):
    whatsapp.send_text(
        phone,
        f"📞 *Talk to Our Team*\n\n"
        f"*Phone / WhatsApp:* {_s("property_contact", config.PROPERTY_CONTACT)}\n"
        f"*Email:* {_s("support_email", config.SUPPORT_EMAIL)}\n\n"
        "Available: 8 AM – 8 PM daily 🌾\n\n"
        "Type *Hi* to restart the chatbot anytime.",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# ── INFO / EXPLORE FLOW ───────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

def _show_info_menu(phone: str):
    s = _session(phone)
    whatsapp.send_list(
        phone,
        f"Great, *{s.get('guest_name','there')}*! 🌿\n\n"
        f"What would you like to know about *{_s("property_name", config.PROPERTY_NAME)}*?",
        "Browse Topics",
        [
            {
                "title": "Property",
                "rows": [
                    {"id": "inf_rooms",     "title": "Rooms & Facilities",  "description": "Room types, bathrooms, amenities"},
                    {"id": "inf_food",      "title": "Food & Dining",       "description": "Meal options, veg/non-veg, prices"},
                    {"id": "inf_pricing",   "title": "Pricing & Tariff",    "description": "Room rates, extra charges"},
                ],
            },
            {
                "title": "Activities & Logistics",
                "rows": [
                    {"id": "inf_activities","title": "Activities & Games",  "description": "Day 1 & Day 2 activities"},
                    {"id": "inf_transport", "title": "Transport & Location","description": "Pickup points, GPS, directions"},
                    {"id": "inf_photos",    "title": "Farm Photos",         "description": "View our farm gallery"},
                    {"id": "inf_medical",   "title": "Medical & Safety",    "description": "Hospital, pharmacy, emergency"},
                ],
            },
        ],
    )
    _state(phone, "INFO_MENU")


def _info_menu(phone: str, content: str):
    if content == "path_book":
        _start_booking(phone)
        return
    dispatch = {
        "inf_rooms":      _info_rooms,
        "inf_food":       _info_food,
        "inf_pricing":    _info_pricing,
        "inf_activities": _info_activities,
        "inf_transport":  _info_transport,
        "inf_photos":     _info_photos,
        "inf_medical":    _info_medical,
    }
    fn = dispatch.get(content)
    if fn:
        fn(phone)
    else:
        whatsapp.send_text(phone, "Please select a topic from the menu.")


def _more_details_line() -> str:
    """Standard 'visit our website' footer used at the end of every info topic."""
    url = config.BASE_URL.rstrip("/") + "/"
    return f"For more details, visit our website 👇\n{url}"


def _info_back(phone: str):
    """Send back/book buttons after every info response."""
    whatsapp.send_buttons(
        phone,
        "What would you like to do next?",
        [
            {"id": "inf_back", "title": "Back to Menu"},
            {"id": "path_book","title": "Book a Stay"},
        ],
    )
    _state(phone, "INFO_BACK")


def _handle_info_back(phone: str, content: str):
    if content == "path_book":
        _start_booking(phone)
    else:
        _show_info_menu(phone)


def _info_rooms(phone: str):
    lines = "\n".join(f"  {k}: {v}" for k, v in config.FACILITIES.items())
    whatsapp.send_text(
        phone,
        f"🏠 *Rooms & Facilities — {_s("property_name", config.PROPERTY_NAME)}*\n\n"
        f"*Room Types:*\n"
        f"  🏡 Family Suite — up to 4 guests | Rs.{pricing.ROOM_RATES['Family Suite']:,}/night\n"
        f"  🛏️ Dormitory Stay — up to 6 guests | Rs.{pricing.ROOM_RATES['Dormitory Stay']:,}/night\n\n"
        f"*Facilities:*\n{lines}\n\n"
        f"*Check-in:* {_s("check_in_time", config.CHECK_IN_TIME)}  |  *Check-out:* {_s("check_out_time", config.CHECK_OUT_TIME)}\n\n"
        f"{_more_details_line()}",
    )
    _info_back(phone)


def _info_food(phone: str):
    whatsapp.send_text(
        phone,
        f"🍽️ *Food & Dining — {_s("property_name", config.PROPERTY_NAME)}*\n\n"
        "Fresh home-cooked meals, both Veg & Non-Veg.\n\n"
        "*Meal Prices (per person):*\n"
        f"  Breakfast: Rs.{pricing.MEAL_PRICES['Breakfast']:,}\n"
        f"  Lunch:     Rs.{pricing.MEAL_PRICES['Lunch']:,}\n"
        f"  Dinner:    Rs.{pricing.MEAL_PRICES['Dinner']:,}\n\n"
        "*Meal Combos:*\n"
        + "\n".join(f"  {k}: Rs.{v:,}/pax" for k, v in pricing.MEAL_COMBOS.items() if v > 0)
        + f"\n\n{_more_details_line()}",
    )
    _info_back(phone)


def _info_pricing(phone: str):
    whatsapp.send_text(
        phone,
        f"💰 *Pricing & Tariff — {_s("property_name", config.PROPERTY_NAME)}*\n\n"
        f"*Rooms (per night):*\n"
        f"  Family Suite:   Rs.{pricing.ROOM_RATES['Family Suite']:,} (up to 4 pax)\n"
        f"  Dormitory Stay: Rs.{pricing.ROOM_RATES['Dormitory Stay']:,} (up to 6 pax)\n\n"
        f"*Meals:* Rs.{pricing.MEAL_PRICES['Breakfast']:,} / Rs.{pricing.MEAL_PRICES['Lunch']:,} / Rs.{pricing.MEAL_PRICES['Dinner']:,} per person\n\n"
        f"*Pickup Transport:*\n"
        + "\n".join(f"  {k}: Rs.{v:,} base" for k, v in pricing.PICKUP_POINTS.items())
        + f"\n\n{config.PAYMENT_INFO}\n\n"
        f"{_more_details_line()}",
    )
    _info_back(phone)


def _act_price_str(v: dict) -> str:
    return "Free" if v["free"] else f"Rs.{v['price']:,}/{v['per']}"


def _info_activities(phone: str):
    d1 = "\n".join(
        f"  {_act_price_str(v)} — {k} ({v['duration']})"
        for k, v in pricing.ACTIVITIES_D1.items()
    )
    d2 = "\n".join(
        f"  {_act_price_str(v)} — {k} ({v['duration']})"
        + (f" _{v.get('note','')}_ " if v.get("note") else "")
        for k, v in pricing.ACTIVITIES_D2.items()
    )
    whatsapp.send_text(
        phone,
        f"🎯 *Activities — {_s("property_name", config.PROPERTY_NAME)}*\n\n"
        f"*Day 1 (On-Farm):*\n{d1}\n\n"
        f"*Day 2 (Off-Farm / Outdoor):*\n{d2}\n\n"
        f"{_more_details_line()}",
    )
    _info_back(phone)


def _info_transport(phone: str):
    pts = "\n".join(f"  {k}: Rs.{v:,} base" for k, v in pricing.PICKUP_POINTS.items())
    whatsapp.send_text(
        phone,
        f"🚗 *Transport & Location — {_s("property_name", config.PROPERTY_NAME)}*\n\n"
        f"*Address:* {_s("property_address", config.PROPERTY_ADDRESS)}\n"
        f"*GPS:* {_s("property_gps", config.PROPERTY_GPS)}\n\n"
        f"*Pickup Points (base rate):*\n{pts}\n\n"
        f"*Vehicle Options:*\n"
        f"  Sedan (4-seat) · MUV (6-7 seat) · Charter Bus (20+ pax)\n\n"
        f"*Contacts:*\n"
        f"  Driver: {_s("transport_contact", config.TRANSPORT_CONTACT)}\n"
        f"  Guide:  {_s("tour_guide_contact", config.TOUR_GUIDE_CONTACT)}\n"
        f"  Sports: {_s("sports_guide_contact", config.SPORTS_GUIDE_CONTACT)}\n\n"
        f"{_more_details_line()}",
    )
    _info_back(phone)


def _info_photos(phone: str):
    whatsapp.send_text(
        phone,
        f"📸 *Farm Photos — {_s("property_name", config.PROPERTY_NAME)}*\n\n"
        "Or contact us directly for photos:\n"
        f"📞 {_s("property_contact", config.PROPERTY_CONTACT)}\n"
        f"📧 {_s("support_email", config.SUPPORT_EMAIL)}\n\n"
        "We'll send photos of rooms, farm, dining, pool & surrounding nature! 🌿\n\n"
        f"{_more_details_line()}",
    )
    _info_back(phone)


def _info_medical(phone: str):
    whatsapp.send_text(
        phone,
        f"🏥 *Medical & Safety — {_s("property_name", config.PROPERTY_NAME)}*\n\n"
        f"Nearest Hospital: {_s("nearest_hospital", config.NEAREST_HOSPITAL)}\n"
        f"Hospital Contact: {_s("medical_contact", config.MEDICAL_CONTACT)}\n"
        f"Ambulance (free): {_s("ambulance", config.AMBULANCE)}\n"
        f"{_s("pharmacy_info", config.PHARMACY_INFO)}\n\n"
        "First-aid kit available at the farm.\n"
        "Caretaker on-site 24/7.\n\n"
        f"{_more_details_line()}",
    )
    _info_back(phone)


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN DISPATCHER
# ═══════════════════════════════════════════════════════════════════════════════

_HANDLERS = {
    "ASK_NAME":               _ask_name,
    "ASK_PATH":               _ask_path,
    # booking
    "ASK_EMAIL":              _ask_email,
    "ASK_ADULTS":             _ask_adults,
    "ASK_CHILDREN":           _ask_children,
    "ASK_CHECKIN":            _ask_checkin,
    "ASK_CHECKOUT":           _ask_checkout,
    "ASK_SPECIAL_REQUESTS":   _ask_special_requests_input,
    "ASK_ROOM_TYPE":          _ask_room_type,
    "ASK_ROOM_COUNT":         _ask_room_count,
    "ROOM_UNAVAILABLE":       _room_unavailable,
    "ASK_FOOD_PREF":          _ask_food_pref,
    "ASK_VEG_COUNT":          _ask_veg_count,
    "ASK_MEALS_D1":           _ask_meals_d1_input,
    "ASK_MEALS_SUB":          _ask_meals_sub,
    "ASK_TRANSPORT_NEEDED":   _ask_transport_needed,
    "ASK_ARRIVAL_MODE":       _ask_arrival_mode,
    "ASK_VEHICLE_TYPE":       _ask_vehicle_type,
    "ASK_ACTIVITIES":         _ask_activities,
    "ASK_ACTIVITY_COUNT":     _ask_activity_count,
    "SHOW_POLICY":            _handle_policy,
    "CONFIRM_BOOKING":        _confirm_booking,
    # info
    "INFO_MENU":              _info_menu,
    "INFO_BACK":              _handle_info_back,
}

_RESET_WORDS = {"hi", "hello", "hey", "start", "restart"}
_INFO_WORDS  = {"info", "explore", "menu", "details", "property"}
_BOOK_WORDS  = {"book", "booking", "reserve"}
_CALL_WORDS  = {"call", "contact", "help", "agent", "human"}


def handle_message(phone: str, msg_type: str, content: str):
    content_lower = content.lower().strip()

    # Greeting → reset
    if content_lower in _RESET_WORDS:
        SESSIONS.pop(phone, None)

    s     = _session(phone)
    state = s["state"]

    # Initial welcome
    if state == "WELCOME":
        _welcome(phone)
        return

    # Global shortcuts
    if content_lower == "back":
        _back(phone)
        return

    if content_lower in _CALL_WORDS:
        _send_contact_info(phone)
        return

    if content_lower in _INFO_WORDS and state not in ("ASK_NAME", "ASK_PATH"):
        _send_explore_link(phone)
        return

    if content_lower in _BOOK_WORDS and state not in ("ASK_NAME", "ASK_PATH"):
        _start_booking(phone)
        return

    # Route to state handler
    handler = _HANDLERS.get(state)
    if handler:
        handler(phone, content)
    else:
        whatsapp.send_text(
            phone,
            f"Type *Hi* to start fresh, or *Menu* to browse property info.\n\n"
            f"Need help? Type *Call* to reach our team.",
        )
