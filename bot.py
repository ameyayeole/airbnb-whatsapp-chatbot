"""
bot.py — Mondkar Farm Stay WhatsApp Chatbot
Character: Mondy 🤖

Flow A — Explore the Farm  (info / FAQ)
Flow B — Book a Stay       (8-step guided booking)
"""
import re
from datetime import date, timedelta
import whatsapp
import database
import pricing
import config

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
            # activities
            "activities_d1":     [],
            "activities_d2":     [],
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
# ── ENTRY ─────────────────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

def _welcome(phone: str):
    whatsapp.send_text(
        phone,
        f"🌾 *Welcome to {config.PROPERTY_NAME}!*\n\n"
        f"I'm *{config.BOT_NAME}* 🤖, your farm concierge.\n\n"
        "May I know your *name* to get started?",
    )
    _state(phone, "ASK_NAME")


def _ask_name(phone: str, content: str):
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
        "What's your *email address*? _(Type 'skip' to skip)_",
    )
    _state(phone, "ASK_EMAIL")


# ── Step 1: Guest Details ─────────────────────────────────────────────────────

def _ask_email(phone: str, content: str):
    email = None if content.lower().strip() == "skip" else content.strip()
    _set(phone, "email", email)
    whatsapp.send_text(phone, "How many *adults* will be staying?\nEnter a number:")
    _state(phone, "ASK_ADULTS")


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
        "_(e.g. anniversary setup, early check-in, dietary needs — or type 'none')_".format(ci=config.CHECK_IN_TIME, co=config.CHECK_OUT_TIME),
    )
    _state(phone, "ASK_SPECIAL_REQUESTS")


def _ask_special_requests_input(phone: str, content: str):
    req = None if content.lower().strip() == "none" else content.strip()
    _set(phone, "special_requests", req)

    # ── Step 3: Room Type ─────────────────────────────────────────────────────
    whatsapp.send_buttons(
        phone,
        "Which room type would you like? 🏡\n\n"
        "• *Family Suite* — private, up to 4 guests\n"
        "• *Dormitory Stay* — shared-style, up to 6 guests",
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

    s    = _session(phone)
    pax  = _pax(phone)
    limit = pricing.ROOM_PAX_LIMIT.get(room, 6)

    if pax > limit:
        whatsapp.send_text(
            phone,
            f"The *{room}* accommodates up to *{limit} guests*. "
            f"Your group has *{pax}*.\n\nPlease select a different room or adjust guest count.",
        )
        return

    _set(phone, "room_type", room)

    # Check availability
    if not database.check_availability(s["check_in"], s["check_out"], room):
        whatsapp.send_buttons(
            phone,
            f"😔 Sorry! *{room}* is not available for *{s['check_in']} → {s['check_out']}*.\n\n"
            "Would you like to try different dates or the other room type?",
            [
                {"id": "retry_dates", "title": "Different Dates"},
                {"id": "retry_room",  "title": "Other Room Type"},
            ],
        )
        _state(phone, "ROOM_UNAVAILABLE")
        return

    # ── Step 4: Meal Planning ─────────────────────────────────────────────────
    whatsapp.send_list(
        phone,
        f"*{room}* is available ✅\n\n"
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
        other = "Dormitory Stay" if _session(phone).get("room_type") == "Family Suite" else "Family Suite"
        s = _session(phone)
        limit = pricing.ROOM_PAX_LIMIT.get(other, 6)
        pax = _pax(phone)
        if pax > limit:
            whatsapp.send_text(phone, f"The *{other}* also has a limit of {limit} guests. Please try different dates.")
            _state(phone, "ASK_CHECKIN")
            return
        _set(phone, "room_type", other)
        if not database.check_availability(s["check_in"], s["check_out"], other):
            whatsapp.send_text(phone, "😔 Unfortunately both room types are booked for those dates. Please try different dates.")
            _state(phone, "ASK_CHECKIN")
        else:
            _set(phone, "room_type", other)
            _ask_food_pref_step(phone)
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
    whatsapp.send_list(
        phone,
        "How will you be *arriving*? 🚗",
        "Select Mode",
        [{"title": "Mode of Arrival", "rows": [
            {"id": "arr_self",      "title": "Self-Drive",           "description": "Own vehicle"},
            {"id": "arr_kudal",     "title": "Kudal Railway",        "description": f"Rs.{pricing.PICKUP_POINTS['Kudal Railway Station']:,} base"},
            {"id": "arr_sawant",    "title": "Sawantwadi Railway",   "description": f"Rs.{pricing.PICKUP_POINTS['Sawantwadi Railway Station']:,} base"},
            {"id": "arr_mopa",      "title": "Mopa Airport",         "description": f"Rs.{pricing.PICKUP_POINTS['Mopa Airport']:,} base"},
            {"id": "arr_chipi",     "title": "Chipi Airport",        "description": f"Rs.{pricing.PICKUP_POINTS['Chipi Airport']:,} base"},
        ]}],
    )
    _state(phone, "ASK_ARRIVAL_MODE")


_ARRIVAL_MAP = {
    "arr_self":   ("Self-Drive",              None),
    "arr_kudal":  ("Railway",  "Kudal Railway Station"),
    "arr_sawant": ("Railway",  "Sawantwadi Railway Station"),
    "arr_mopa":   ("Flight",   "Mopa Airport"),
    "arr_chipi":  ("Flight",   "Chipi Airport"),
}


def _ask_arrival_mode(phone: str, content: str):
    result = _ARRIVAL_MAP.get(content)
    if not result:
        whatsapp.send_text(phone, "Please select from the list.")
        return
    mode, pickup = result
    _set(phone, "arrival_mode",  mode)
    _set(phone, "pickup_point",  pickup)

    if mode == "Self-Drive":
        _set(phone, "vehicle_type", None)
        _ask_activities_d1_step(phone)
    else:
        pax = _pax(phone)
        whatsapp.send_list(
            phone,
            f"What type of *vehicle* do you need for pickup?\n_{pax} guests to transport_",
            "Select Vehicle",
            [{"title": "Vehicle Type", "rows": [
                {"id": "veh_sedan", "title": "Sedan",        "description": "4-seater car"},
                {"id": "veh_muv",   "title": "MUV",          "description": "6-7 seater MUV"},
                {"id": "veh_bus",   "title": "Charter Bus",  "description": "Large group (20+ pax)"},
            ]}],
        )
        _state(phone, "ASK_VEHICLE_TYPE")


def _ask_vehicle_type(phone: str, content: str):
    veh_map = {"veh_sedan": "Sedan", "veh_muv": "MUV", "veh_bus": "Charter Bus"}
    veh = veh_map.get(content)
    if not veh:
        whatsapp.send_text(phone, "Please select a vehicle type from the list.")
        return
    _set(phone, "vehicle_type", veh)
    _ask_activities_d1_step(phone)


# ── Step 6: Activities ────────────────────────────────────────────────────────

def _ask_activities_d1_step(phone: str):
    s      = _session(phone)
    chosen = ", ".join(s["activities_d1"]) or "None selected"
    whatsapp.send_list(
        phone,
        f"Selected so far: *{chosen}*\n\n"
        "Pick a *Day 1 activity* (on the farm):",
        "Select",
        [{"title": "Day 1 — Farm Activities", "rows": [
            {"id": "d1_petting", "title": "Animal Petting",          "description": "Free · 1 hour"},
            {"id": "d1_bullock", "title": "Bullock Cart Ride",       "description": "Rs.100/pax · 15 mins"},
            {"id": "d1_bkfast",  "title": "Pick Breakfast Plate",    "description": "Rs.300/pax · 30 mins"},
            {"id": "d1_trek",    "title": "Trekking",                "description": "Free · 2 hours"},
            {"id": "d1_swim",    "title": "Swimming Pool",           "description": "Free · All day"},
            {"id": "d1_rain",    "title": "Gazebo Rain Dance",       "description": "Rs.150/pax · 2 hours"},
            {"id": "d1_games",   "title": "Indoor Games",            "description": "Rs.150/pax · 3-4 hours"},
            {"id": "d1_none",    "title": "No Activities",           "description": "Skip & continue"},
        ]}],
    )
    _state(phone, "ASK_ACTIVITIES_D1")


_D1_MAP = {
    "d1_petting": "Animal Petting",
    "d1_bullock": "Bullock Cart Ride",
    "d1_bkfast":  "Pick Your Breakfast Plate",
    "d1_trek":    "Trekking",
    "d1_swim":    "Swimming Pool",
    "d1_rain":    "Gazebo Rain Dance",
    "d1_games":   "Indoor Games",
    "d1_none":    None,
}


def _ask_activities_d1(phone: str, content: str):
    s = _session(phone)
    if content == "d1_none":
        s["activities_d1"] = []
        _ask_activities_d2_step(phone)
        return
    act = _D1_MAP.get(content)
    if act is None:
        whatsapp.send_text(phone, "Please select from the list.")
        return
    if act not in s["activities_d1"]:
        s["activities_d1"].append(act)
    chosen = ", ".join(s["activities_d1"])
    whatsapp.send_buttons(
        phone,
        f"Added ✅ *{act}*\nSelected: *{chosen}*\n\nAdd more or done?",
        [
            {"id": "d1_more", "title": "Add More"},
            {"id": "d1_done", "title": "Done"},
        ],
    )
    _state(phone, "ASK_ACTIVITIES_D1_DONE")


def _ask_activities_d1_done(phone: str, content: str):
    if content == "d1_more":
        _ask_activities_d1_step(phone)
    else:
        _ask_activities_d2_step(phone)


def _ask_activities_d2_step(phone: str):
    s      = _session(phone)
    chosen = ", ".join(s["activities_d2"]) or "None selected"
    whatsapp.send_list(
        phone,
        f"Selected so far: *{chosen}*\n\n"
        "Pick a *Day 2 activity* (off-farm / outdoor):",
        "Select",
        [{"title": "Day 2 — Outdoor Adventures", "rows": [
            {"id": "d2_kayak",   "title": "Kayaking",                 "description": "Rs.400/boat · 1 hour"},
            {"id": "d2_beach",   "title": "Beach & Temple Visit",     "description": "Free · Transport charges apply"},
            {"id": "d2_malvan",  "title": "Malvan Water Sports",      "description": "Free · Local fare applies"},
            {"id": "d2_vengurla","title": "Vengurla Beach",           "description": "Free · Transport charges apply"},
            {"id": "d2_none",    "title": "No Activities",            "description": "Skip & continue"},
        ]}],
    )
    _state(phone, "ASK_ACTIVITIES_D2")


_D2_MAP = {
    "d2_kayak":    "Kayaking",
    "d2_beach":    "Beach & Temple Visit",
    "d2_malvan":   "Malvan Water Sports",
    "d2_vengurla": "Vengurla Beach Exploration",
    "d2_none":     None,
}


def _ask_activities_d2(phone: str, content: str):
    s = _session(phone)
    if content == "d2_none":
        s["activities_d2"] = []
        _show_policy(phone)
        return
    act = _D2_MAP.get(content)
    if act is None:
        whatsapp.send_text(phone, "Please select from the list.")
        return
    if act not in s["activities_d2"]:
        s["activities_d2"].append(act)
    chosen = ", ".join(s["activities_d2"])
    whatsapp.send_buttons(
        phone,
        f"Added ✅ *{act}*\nSelected: *{chosen}*\n\nAdd more or done?",
        [
            {"id": "d2_more", "title": "Add More"},
            {"id": "d2_done", "title": "Done"},
        ],
    )
    _state(phone, "ASK_ACTIVITIES_D2_DONE")


def _ask_activities_d2_done(phone: str, content: str):
    if content == "d2_more":
        _ask_activities_d2_step(phone)
    else:
        _show_policy(phone)


# ── Step 7: Policy ────────────────────────────────────────────────────────────

def _show_policy(phone: str):
    whatsapp.send_buttons(
        phone,
        f"📜 *Booking Policy — Please Read*\n\n"
        f"{config.CANCELLATION_POLICY}\n\n"
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
    )
    SESSIONS[phone]["_totals"] = totals

    advance = round(totals["total"] * config.ADVANCE_PERCENT / 100)

    d1_acts = ", ".join(s["activities_d1"]) or "None"
    d2_acts = ", ".join(s["activities_d2"]) or "None"
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
        f"📋 *Booking Summary — {config.PROPERTY_NAME}*\n\n"
        f"*Name:*    {s['guest_name']}\n"
        f"*Guests:*  {s['adults']} adult(s), {s['children']} child(ren)\n"
        f"*Email:*   {s.get('email') or 'Not provided'}\n\n"
        f"*Check-in:*  {ci.strftime('%d %b %Y')}  {config.CHECK_IN_TIME}\n"
        f"*Check-out:* {co.strftime('%d %b %Y')}  {config.CHECK_OUT_TIME}\n"
        f"*Nights:*    {s['nights']}\n\n"
        f"*Room:*     {s['room_type']}\n"
        f"*Food:*     {s['food_preference']} "
        f"({s['veg_count']} Veg / {s['nv_count']} Non-Veg)\n"
        f"*Meals:*    {meals}\n\n"
        f"*Day 1 Activities:* {d1_acts}\n"
        f"*Day 2 Activities:* {d2_acts}\n\n"
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
        f"*Room:* {s['room_type']}\n"
        f"*Total:* Rs.{totals.get('total',0):,}\n\n"
        f"{config.PAYMENT_INFO}\n\n"
        f"*Please pay the advance of Rs.{advance:,} to confirm your slot.*",
    )

    # 2. Arrival info
    whatsapp.send_text(
        phone,
        f"📍 *Farm Details*\n\n"
        f"*Address:* {config.PROPERTY_ADDRESS}\n"
        f"*GPS:* {config.PROPERTY_GPS}\n\n"
        f"*Check-in:*  {config.CHECK_IN_TIME}\n"
        f"*Check-out:* {config.CHECK_OUT_TIME}\n\n"
        f"*Contact:* {config.PROPERTY_CONTACT}\n"
        f"*Email:* {config.SUPPORT_EMAIL}\n\n"
        "_Please carry a valid Govt. Photo ID._",
    )

    # 3. Packing + climate
    climate = config.CLIMATE_BY_MONTH.get(ci.month, "Expect pleasant weather.")
    whatsapp.send_text(
        phone,
        "*What to Carry*\n\n"
        + "\n".join(config.THINGS_TO_CARRY)
        + f"\n\n*Climate during your stay:*\n{climate}",
    )

    # 4. Medical
    whatsapp.send_text(
        phone,
        f"🏥 *Medical & Emergency*\n\n"
        f"Nearest Hospital: {config.NEAREST_HOSPITAL}\n"
        f"Contact: {config.MEDICAL_CONTACT}\n"
        f"Ambulance: {config.AMBULANCE}\n"
        f"{config.PHARMACY_INFO}",
    )

    # 5. Farewell
    whatsapp.send_text(
        phone,
        f"🌾 *Thank you for choosing {config.PROPERTY_NAME}!*\n\n"
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
        f"*Phone / WhatsApp:* {config.PROPERTY_CONTACT}\n"
        f"*Email:* {config.SUPPORT_EMAIL}\n\n"
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
        f"What would you like to know about *{config.PROPERTY_NAME}*?",
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
                    {"id": "inf_climate",   "title": "Climate & Packing",   "description": "Weather & what to bring"},
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
        "inf_climate":    _info_climate,
        "inf_medical":    _info_medical,
    }
    fn = dispatch.get(content)
    if fn:
        fn(phone)
    else:
        whatsapp.send_text(phone, "Please select a topic from the menu.")


def _info_back(phone: str):
    """Send back/book buttons after every info response."""
    whatsapp.send_buttons(
        phone, "What would you like to do next?",
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
        f"🏠 *Rooms & Facilities — {config.PROPERTY_NAME}*\n\n"
        f"*Room Types:*\n"
        f"  🏡 Family Suite — up to 4 guests | Rs.{pricing.ROOM_RATES['Family Suite']:,}/night\n"
        f"  🛏️ Dormitory Stay — up to 6 guests | Rs.{pricing.ROOM_RATES['Dormitory Stay']:,}/night\n\n"
        f"*Facilities:*\n{lines}\n\n"
        f"*Check-in:* {config.CHECK_IN_TIME}  |  *Check-out:* {config.CHECK_OUT_TIME}\n\n"
        f"📎 Full details: {config.WEBSITE_URL}/rooms",
    )
    _info_back(phone)


def _info_food(phone: str):
    whatsapp.send_text(
        phone,
        f"🍽️ *Food & Dining — {config.PROPERTY_NAME}*\n\n"
        "Fresh home-cooked meals, both Veg & Non-Veg.\n\n"
        "*Meal Prices (per person):*\n"
        f"  Breakfast: Rs.{pricing.MEAL_PRICES['Breakfast']:,}\n"
        f"  Lunch:     Rs.{pricing.MEAL_PRICES['Lunch']:,}\n"
        f"  Dinner:    Rs.{pricing.MEAL_PRICES['Dinner']:,}\n\n"
        "*Meal Combos:*\n"
        + "\n".join(f"  {k}: Rs.{v:,}/pax" for k, v in pricing.MEAL_COMBOS.items() if v > 0)
        + f"\n\n📎 Full menu: {config.WEBSITE_URL}/food",
    )
    _info_back(phone)


def _info_pricing(phone: str):
    whatsapp.send_text(
        phone,
        f"💰 *Pricing & Tariff — {config.PROPERTY_NAME}*\n\n"
        f"*Rooms (per night):*\n"
        f"  Family Suite:   Rs.{pricing.ROOM_RATES['Family Suite']:,} (up to 4 pax)\n"
        f"  Dormitory Stay: Rs.{pricing.ROOM_RATES['Dormitory Stay']:,} (up to 6 pax)\n\n"
        f"*Meals:* Rs.{pricing.MEAL_PRICES['Breakfast']:,} / Rs.{pricing.MEAL_PRICES['Lunch']:,} / Rs.{pricing.MEAL_PRICES['Dinner']:,} per person\n\n"
        f"*Pickup Transport:*\n"
        + "\n".join(f"  {k}: Rs.{v:,} base" for k, v in pricing.PICKUP_POINTS.items())
        + f"\n\n{config.PAYMENT_INFO}\n\n"
        f"📎 More: {config.WEBSITE_URL}/pricing",
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
        f"🎯 *Activities — {config.PROPERTY_NAME}*\n\n"
        f"*Day 1 (On-Farm):*\n{d1}\n\n"
        f"*Day 2 (Off-Farm / Outdoor):*\n{d2}\n\n"
        f"📎 Full info: {config.WEBSITE_URL}/activities",
    )
    _info_back(phone)


def _info_transport(phone: str):
    pts = "\n".join(f"  {k}: Rs.{v:,} base" for k, v in pricing.PICKUP_POINTS.items())
    whatsapp.send_text(
        phone,
        f"🚗 *Transport & Location — {config.PROPERTY_NAME}*\n\n"
        f"*Address:* {config.PROPERTY_ADDRESS}\n"
        f"*GPS:* {config.PROPERTY_GPS}\n\n"
        f"*Pickup Points (base rate):*\n{pts}\n\n"
        f"*Vehicle Options:*\n"
        f"  Sedan (4-seat) · MUV (6-7 seat) · Charter Bus (20+ pax)\n\n"
        f"*Contacts:*\n"
        f"  Driver: {config.TRANSPORT_CONTACT}\n"
        f"  Guide:  {config.TOUR_GUIDE_CONTACT}\n"
        f"  Sports: {config.SPORTS_GUIDE_CONTACT}\n\n"
        f"📎 Directions: {config.WEBSITE_URL}/location",
    )
    _info_back(phone)


def _info_photos(phone: str):
    whatsapp.send_text(
        phone,
        f"📸 *Farm Photos — {config.PROPERTY_NAME}*\n\n"
        f"View our full photo gallery online:\n"
        f"👉 {config.WEBSITE_URL}/gallery\n\n"
        "Or contact us directly for photos:\n"
        f"📞 {config.PROPERTY_CONTACT}\n"
        f"📧 {config.SUPPORT_EMAIL}\n\n"
        "We'll send photos of rooms, farm, dining, pool & surrounding nature! 🌿",
    )
    _info_back(phone)


def _info_climate(phone: str):
    month   = date.today().month
    current = config.CLIMATE_BY_MONTH.get(month, "Expect pleasant weather.")
    items   = "\n".join(config.THINGS_TO_CARRY)
    whatsapp.send_text(
        phone,
        f"🌤️ *Climate & Packing — {config.PROPERTY_NAME}*\n\n"
        f"*Current Month:* {current}\n\n"
        f"*What to Pack:*\n{items}\n\n"
        f"📎 Seasonal guide: {config.WEBSITE_URL}/climate",
    )
    _info_back(phone)


def _info_medical(phone: str):
    whatsapp.send_text(
        phone,
        f"🏥 *Medical & Safety — {config.PROPERTY_NAME}*\n\n"
        f"Nearest Hospital: {config.NEAREST_HOSPITAL}\n"
        f"Hospital Contact: {config.MEDICAL_CONTACT}\n"
        f"Ambulance (free): {config.AMBULANCE}\n"
        f"{config.PHARMACY_INFO}\n\n"
        "First-aid kit available at the farm.\n"
        "Caretaker on-site 24/7.",
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
    "ROOM_UNAVAILABLE":       _room_unavailable,
    "ASK_FOOD_PREF":          _ask_food_pref,
    "ASK_VEG_COUNT":          _ask_veg_count,
    "ASK_MEALS_D1":           _ask_meals_d1_input,
    "ASK_MEALS_SUB":          _ask_meals_sub,
    "ASK_ARRIVAL_MODE":       _ask_arrival_mode,
    "ASK_VEHICLE_TYPE":       _ask_vehicle_type,
    "ASK_ACTIVITIES_D1":      _ask_activities_d1,
    "ASK_ACTIVITIES_D1_DONE": _ask_activities_d1_done,
    "ASK_ACTIVITIES_D2":      _ask_activities_d2,
    "ASK_ACTIVITIES_D2_DONE": _ask_activities_d2_done,
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
    if content_lower in _CALL_WORDS:
        _send_contact_info(phone)
        return

    if content_lower in _INFO_WORDS and state not in ("ASK_NAME", "ASK_PATH"):
        _show_info_menu(phone)
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
