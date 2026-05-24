"""
bot.py — Farm-stay WhatsApp chatbot
Two parallel flows:
  • BOOKING  — full guest-profiling → rooms → food → activities → transport → confirm
  • INFO     — property FAQ branch accessible anytime via keyword or menu
"""
import re
from datetime import datetime, date
import whatsapp
import database
import pricing
import config

# ═══════════════════════════════════════════════════════════════════════════════
# SESSION STORE
# ═══════════════════════════════════════════════════════════════════════════════

SESSIONS: dict = {}


def _session(phone: str) -> dict:
    if phone not in SESSIONS:
        SESSIONS[phone] = {
            "state":              "WELCOME",
            # guest profile
            "guest_name":         None,
            "client_type":        None,
            "interests":          None,
            "arrival_medium":     None,
            # dates / rooms
            "check_in":           None,
            "check_out":          None,
            "nights":             None,
            "room_type":          None,
            "rooms_count":        1,
            "pax":                None,
            # food
            "food_preferences":   None,
            "meal_plan":          "No Meals",
            "meal_location":      "In-house",
            # activities / transport
            "activities":         [],
            "transport":          None,
            "internal_transport": None,
            # internal
            "_totals":            None,
        }
    return SESSIONS[phone]


def _set_state(phone: str, state: str):
    SESSIONS[phone]["state"] = state


def _s(phone: str, key: str, value):
    SESSIONS[phone][key] = value


# ═══════════════════════════════════════════════════════════════════════════════
# DATE PARSING
# ═══════════════════════════════════════════════════════════════════════════════

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10,
    "november": 11, "december": 12,
}


def _parse_date_range(text: str):
    text = text.lower().strip()
    yr = date.today().year
    mp = "|".join(sorted(_MONTHS.keys(), key=len, reverse=True))

    # DD/MM/YYYY to DD/MM/YYYY
    m = re.match(
        r"(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})\s*(?:to|[-–])\s*(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})", text)
    if m:
        ci = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        co = date(int(m.group(6)), int(m.group(5)), int(m.group(4)))
        return ci, co, (co - ci).days

    # "4 June 2026 to 6 June 2026"
    m = re.match(rf"(\d{{1,2}})\w*\s+({mp})\s+(\d{{4}})\s*(?:to|[-–])\s*(\d{{1,2}})\w*\s+({mp})\s+(\d{{4}})", text)
    if m:
        ci = date(int(m.group(3)), _MONTHS[m.group(2)], int(m.group(1)))
        co = date(int(m.group(6)), _MONTHS[m.group(5)], int(m.group(4)))
        return ci, co, (co - ci).days

    # "4 June 2026 to 6 June"
    m = re.match(rf"(\d{{1,2}})\w*\s+({mp})\s+(\d{{4}})\s*(?:to|[-–])\s*(\d{{1,2}})\w*\s+({mp})", text)
    if m:
        y = int(m.group(3))
        ci = date(y, _MONTHS[m.group(2)], int(m.group(1)))
        co = date(y, _MONTHS[m.group(5)], int(m.group(4)))
        if co <= ci:
            co = co.replace(year=y + 1)
        return ci, co, (co - ci).days

    # "4 June to 6 June"
    m = re.match(rf"(\d{{1,2}})\w*\s+({mp})\s*(?:to|[-–])\s*(\d{{1,2}})\w*\s+({mp})", text)
    if m:
        ci = date(yr, _MONTHS[m.group(2)], int(m.group(1)))
        co = date(yr, _MONTHS[m.group(4)], int(m.group(3)))
        if co <= ci:
            co = co.replace(year=yr + 1)
        return ci, co, (co - ci).days

    # "4-6 June 2026"
    m = re.match(rf"(\d{{1,2}})\w*\s*[-–]\s*(\d{{1,2}})\w*\s+({mp})\s+(\d{{4}})", text)
    if m:
        y, mo = int(m.group(4)), _MONTHS[m.group(3)]
        ci, co = date(y, mo, int(m.group(1))), date(y, mo, int(m.group(2)))
        return ci, co, (co - ci).days

    # "4-6 June"
    m = re.match(rf"(\d{{1,2}})\w*\s*[-–]\s*(\d{{1,2}})\w*\s+({mp})", text)
    if m:
        mo = _MONTHS[m.group(3)]
        ci = date(yr, mo, int(m.group(1)))
        co = date(yr, mo, int(m.group(2)))
        if co <= ci:
            co = co.replace(year=yr + 1)
        return ci, co, (co - ci).days

    return None


# ═══════════════════════════════════════════════════════════════════════════════
# ── BOOKING FLOW ──────────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

def _welcome(phone: str):
    whatsapp.send_buttons(
        phone,
        f"🌿 *Welcome to {config.PROPERTY_NAME}!*\n\n"
        "A peaceful farm escape in the heart of Goa — fresh food, open fields, "
        "and unforgettable experiences.\n\n"
        "How can I help you today?",
        [
            {"id": "main_book", "title": "Book a Stay"},
            {"id": "main_info", "title": "Property Info"},
        ],
    )
    _set_state(phone, "MAIN_MENU")


def _main_menu(phone: str, content: str):
    if content == "main_book":
        whatsapp.send_text(
            phone,
            "Wonderful! Let's get your booking started. 😊\n\nMay I have your *name*?",
        )
        _set_state(phone, "ASK_NAME")
    elif content == "main_info":
        _show_info_menu(phone)
    else:
        _welcome(phone)


# ── Guest profiling ───────────────────────────────────────────────────────────

def _ask_name(phone: str, content: str):
    name = content.strip().title()
    if len(name) < 2:
        whatsapp.send_text(phone, "Please share your name so I can address you properly 😊")
        return
    _s(phone, "guest_name", name)
    whatsapp.send_list(
        phone,
        f"Great to meet you, *{name}*! 🙏\n\nWhat best describes your group?",
        "Select Type",
        [{"title": "Group Type", "rows": [
            {"id": "ct_family",     "title": "Family",           "description": "With kids / elders"},
            {"id": "ct_friends",    "title": "Friends Group",    "description": "Friends trip"},
            {"id": "ct_business",   "title": "Business Trip",    "description": "Solo / corporate stay"},
            {"id": "ct_conference", "title": "Conference/Event", "description": "Retreat, workshop, event"},
            {"id": "ct_bikers",     "title": "Biking Group",     "description": "Cycling / motorbike tour"},
            {"id": "ct_birdwatch",  "title": "Birdwatching",     "description": "Nature & bird photography"},
            {"id": "ct_wellness",   "title": "Health/Wellness",  "description": "Yoga / detox / wellness"},
        ]}],
    )
    _set_state(phone, "ASK_CLIENT_TYPE")


_CLIENT_TYPE_MAP = {
    "ct_family":     "Family",
    "ct_friends":    "Friends Group",
    "ct_business":   "Business Trip",
    "ct_conference": "Conference / Event",
    "ct_bikers":     "Biking Group",
    "ct_birdwatch":  "Birdwatching Group",
    "ct_wellness":   "Health / Wellness Group",
}


def _ask_client_type(phone: str, content: str):
    ct = _CLIENT_TYPE_MAP.get(content)
    if not ct:
        whatsapp.send_text(phone, "Please select your group type from the list.")
        return
    _s(phone, "client_type", ct)
    whatsapp.send_list(
        phone,
        f"*{ct}* — great! 🌟\n\nWhat is the primary interest for this visit?",
        "Select Interest",
        [{"title": "Primary Interest", "rows": [
            {"id": "int_nature",    "title": "Nature & Wildlife",  "description": "Farm walks, birds, wildlife"},
            {"id": "int_beach",     "title": "Beach & Water",      "description": "Beach, kayaking, watersports"},
            {"id": "int_culture",   "title": "Culture & Heritage", "description": "Temples, churches, local food"},
            {"id": "int_holistic",  "title": "Holistic & Wellness","description": "Yoga, meditation, organic food"},
            {"id": "int_festival",  "title": "Festival & Party",   "description": "Birthday, anniversary, event"},
            {"id": "int_adventure", "title": "Adventure & Outdoor","description": "Hiking, cycling, extreme sports"},
            {"id": "int_solitude",  "title": "Quiet Getaway",      "description": "Relax, read, recharge"},
        ]}],
    )
    _set_state(phone, "ASK_INTERESTS")


_INTEREST_MAP = {
    "int_nature":    "Nature & Wildlife",
    "int_beach":     "Beach & Water Sports",
    "int_culture":   "Culture & Heritage",
    "int_holistic":  "Holistic & Wellness",
    "int_festival":  "Festival & Celebration",
    "int_adventure": "Adventure & Outdoor",
    "int_solitude":  "Quiet Getaway",
}


def _ask_interests(phone: str, content: str):
    interest = _INTEREST_MAP.get(content)
    if not interest:
        whatsapp.send_text(phone, "Please select your primary interest from the list.")
        return
    _s(phone, "interests", interest)
    whatsapp.send_list(
        phone,
        f"*{interest}* — sounds wonderful! 🙌\n\nHow will you be arriving?",
        "Select Mode",
        [{"title": "Mode of Arrival", "rows": [
            {"id": "arr_selfcar",     "title": "Self-Drive (Own Car)",  "description": "Arriving by personal vehicle"},
            {"id": "arr_train",       "title": "Train",                 "description": "Kudal / Kankawali station"},
            {"id": "arr_flight_mopa", "title": "Flight — Mopa Airport", "description": "Sindhudurg (North Goa)"},
            {"id": "arr_flight_goa",  "title": "Flight — Dabolim",      "description": "Goa South (old airport)"},
            {"id": "arr_bus",         "title": "Bus / Public Transport","description": "State or private bus"},
        ]}],
    )
    _set_state(phone, "ASK_ARRIVAL_MEDIUM")


_ARRIVAL_MAP = {
    "arr_selfcar":     "Self-Drive",
    "arr_train":       "Train",
    "arr_flight_mopa": "Flight — Mopa Airport",
    "arr_flight_goa":  "Flight — Dabolim Airport",
    "arr_bus":         "Bus",
}


def _ask_arrival_medium(phone: str, content: str):
    medium = _ARRIVAL_MAP.get(content)
    if not medium:
        whatsapp.send_text(phone, "Please select how you'll be arriving.")
        return
    _s(phone, "arrival_medium", medium)
    whatsapp.send_text(
        phone,
        "Perfect! Now please share your *check-in and check-out dates*. 📅\n\n"
        "Examples:\n"
        "• _4 June 2026 to 6 June 2026_\n"
        "• _4-6 June 2026_\n"
        "• _04/06/2026 to 06/06/2026_",
    )
    _set_state(phone, "ASK_DATES")


# ── Dates → Room type → Guests ────────────────────────────────────────────────

def _ask_dates(phone: str, content: str):
    result = _parse_date_range(content)
    if not result:
        whatsapp.send_text(
            phone,
            "Sorry, I couldn't read those dates. Please try again.\n"
            "Example: _4 June 2026 to 6 June 2026_",
        )
        return
    ci, co, nights = result
    if nights <= 0:
        whatsapp.send_text(phone, "Check-out must be after check-in. Please try again.")
        return
    if ci < date.today():
        whatsapp.send_text(phone, "Check-in date cannot be in the past. Please try again.")
        return

    s = _session(phone)
    s["check_in"]  = ci.isoformat()
    s["check_out"] = co.isoformat()
    s["nights"]    = nights

    season = pricing.seasonal_label(ci.month)
    whatsapp.send_buttons(
        phone,
        f"✅ *{ci.strftime('%d %b %Y')} → {co.strftime('%d %b %Y')}*"
        f" ({nights} night{'s' if nights > 1 else ''})\n_{season}_\n\n"
        "What type of booking do you need?",
        [
            {"id": "room_couple", "title": "Couple / Single Room"},
            {"id": "room_bulk",   "title": "Bulk Booking"},
        ],
    )
    _set_state(phone, "ASK_ROOM_TYPE")


def _ask_room_type(phone: str, content: str):
    if content == "room_couple":
        _s(phone, "room_type", "couple")
        _s(phone, "rooms_count", 1)
        whatsapp.send_text(phone, "How many guests? *(max 3 for a single room)*\nEnter a number:")
        _set_state(phone, "ASK_GUESTS")
    elif content == "room_bulk":
        _s(phone, "room_type", "bulk")
        whatsapp.send_list(
            phone,
            "How many rooms do you need?\n*(4 rooms total; 3 guests max per room)*",
            "Select Rooms",
            [{"title": "Number of Rooms", "rows": [
                {"id": "rooms_2", "title": "2 Rooms", "description": "Up to 6 guests"},
                {"id": "rooms_3", "title": "3 Rooms", "description": "Up to 9 guests"},
                {"id": "rooms_4", "title": "4 Rooms (Entire Property)", "description": "Up to 12 guests"},
            ]}],
        )
        _set_state(phone, "ASK_ROOM_COUNT")
    else:
        whatsapp.send_text(phone, "Please tap one of the options above.")


def _ask_room_count(phone: str, content: str):
    room_map = {"rooms_2": 2, "rooms_3": 3, "rooms_4": 4}
    count = room_map.get(content)
    if count is None:
        whatsapp.send_text(phone, "Please select number of rooms from the list.")
        return
    _s(phone, "rooms_count", count)
    whatsapp.send_text(
        phone,
        f"*{count} room(s)* selected. How many guests in total? *(max {count * 3})*\nEnter a number:",
    )
    _set_state(phone, "ASK_GUESTS")


def _ask_guests(phone: str, content: str):
    if not content.isdigit() or int(content) < 1:
        whatsapp.send_text(phone, "Please enter a valid number of guests (e.g. 4).")
        return
    s = _session(phone)
    pax = int(content)
    max_allowed = s["rooms_count"] * 3
    if pax > max_allowed:
        whatsapp.send_text(
            phone,
            f"Maximum *{max_allowed} guests* for {s['rooms_count']} room(s). "
            f"Please enter up to {max_allowed}:",
        )
        return
    _s(phone, "pax", pax)
    _check_availability_and_proceed(phone)


def _check_availability_and_proceed(phone: str):
    s = _session(phone)
    if not database.check_availability(s["check_in"], s["check_out"], s["rooms_count"]):
        whatsapp.send_buttons(
            phone,
            f"😔 Sorry! *{s['rooms_count']} room(s)* are not available for "
            f"*{s['check_in']} → {s['check_out']}*.\n\nWould you like to try different dates?",
            [
                {"id": "retry_dates",  "title": "Try Different Dates"},
                {"id": "main_restart", "title": "Start Over"},
            ],
        )
        _set_state(phone, "AVAILABILITY_RETRY")
        return

    whatsapp.send_list(
        phone,
        "Rooms are *available* ✅\n\nWhat are your *food preferences*?",
        "Select Preference",
        [{"title": "Dietary Preference", "rows": [
            {"id": "food_veg",    "title": "Vegetarian",     "description": "Veg only"},
            {"id": "food_nonveg", "title": "Non-Vegetarian", "description": "Meat, fish, eggs"},
            {"id": "food_mix",    "title": "Mixed",          "description": "Veg + Non-Veg"},
            {"id": "food_jain",   "title": "Jain",           "description": "No root vegetables"},
            {"id": "food_any",    "title": "No Preference",  "description": "Any food is fine"},
        ]}],
    )
    _set_state(phone, "ASK_FOOD_PREFS")


def _availability_retry(phone: str, content: str):
    if content == "retry_dates":
        whatsapp.send_text(
            phone,
            "Please share your new check-in and check-out dates:\n"
            "Example: _10 July 2026 to 13 July 2026_",
        )
        _set_state(phone, "ASK_DATES")
    else:
        SESSIONS.pop(phone, None)
        _session(phone)
        _welcome(phone)


# ── Food & Meals ──────────────────────────────────────────────────────────────

_FOOD_MAP = {
    "food_veg":    "Vegetarian",
    "food_nonveg": "Non-Vegetarian",
    "food_mix":    "Mixed (Veg + Non-Veg)",
    "food_jain":   "Jain",
    "food_any":    "No Preference",
}


def _ask_food_prefs(phone: str, content: str):
    pref = _FOOD_MAP.get(content)
    if not pref:
        whatsapp.send_text(phone, "Please select your food preference from the list.")
        return
    _s(phone, "food_preferences", pref)
    whatsapp.send_list(
        phone,
        f"Got it — *{pref}*. 🍽️\n\n"
        "Would you like to include *meals* in your booking?\n"
        "_(Freshly prepared at the farmhouse)_",
        "Choose Plan",
        [{"title": "Meal Plans (per person / night)", "rows": [
            {"id": "meal_none", "title": "No Meals",         "description": "Arrange on your own"},
            {"id": "meal_b",    "title": "Breakfast Only",   "description": "Rs.200/person/night"},
            {"id": "meal_l",    "title": "Lunch Only",       "description": "Rs.350/person/night"},
            {"id": "meal_d",    "title": "Dinner Only",      "description": "Rs.400/person/night"},
            {"id": "meal_bd",   "title": "Breakfast+Dinner", "description": "Rs.550/person/night"},
            {"id": "meal_bld",  "title": "All Meals (BLD)",  "description": "Rs.900/person/night"},
        ]}],
    )
    _set_state(phone, "ASK_MEAL_PLAN")


_MEAL_PLAN_MAP = {
    "meal_none": "No Meals",
    "meal_b":    "Breakfast Only",
    "meal_l":    "Lunch Only",
    "meal_d":    "Dinner Only",
    "meal_bd":   "Breakfast+Dinner",
    "meal_bld":  "All Meals (BLD)",
}


def _ask_meal_plan(phone: str, content: str):
    plan = _MEAL_PLAN_MAP.get(content)
    if not plan:
        whatsapp.send_text(phone, "Please select a meal plan from the list.")
        return
    _s(phone, "meal_plan", plan)
    if plan == "No Meals":
        _s(phone, "meal_location", "N/A")
        _ask_activities_step(phone)
    else:
        whatsapp.send_buttons(
            phone,
            f"*Meal Plan:* {plan} ✅\n\n"
            "Would you prefer to *eat in-house* (our cook prepares meals) "
            "or go *outside* for meals?",
            [
                {"id": "meal_inhouse", "title": "Eat In-House"},
                {"id": "meal_outside", "title": "Eat Outside"},
            ],
        )
        _set_state(phone, "ASK_MEAL_LOCATION")


def _ask_meal_location(phone: str, content: str):
    if content == "meal_inhouse":
        _s(phone, "meal_location", "In-house")
    elif content == "meal_outside":
        _s(phone, "meal_location", "Outside (transport arranged)")
    else:
        whatsapp.send_text(phone, "Please tap one of the options above.")
        return
    _ask_activities_step(phone)


# ── Activities (multi-select) ─────────────────────────────────────────────────

def _ask_activities_step(phone: str):
    s = _session(phone)
    chosen = ", ".join(s["activities"]) if s["activities"] else "None"
    whatsapp.send_list(
        phone,
        f"Currently selected: *{chosen}*\n\nPick an *activity* to add (or skip):",
        "Select Activity",
        [
            {
                "title": "Farm Activities",
                "rows": [
                    {"id": "act_veg_pick",    "title": "Veg/Fruit Picking",  "description": "Rs.150/pax"},
                    {"id": "act_animal_pet",  "title": "Animal Petting",     "description": "Rs.150/pax"},
                    {"id": "act_feed_animal", "title": "Feeding Animals",    "description": "Rs.100/pax"},
                    {"id": "act_farm_tour",   "title": "Guided Farm Tour",   "description": "Rs.200/pax"},
                    {"id": "act_kids_zone",   "title": "Kids Activity Zone", "description": "Rs.150/pax"},
                ],
            },
            {
                "title": "Adventure & Outdoor",
                "rows": [
                    {"id": "act_city_tour",  "title": "City Tour",        "description": "Rs.500/pax"},
                    {"id": "act_kayaking",   "title": "Kayaking",         "description": "Rs.400/pax"},
                    {"id": "act_beach",      "title": "Beach Enjoy",      "description": "Rs.300/pax"},
                    {"id": "act_hiking",     "title": "Hiking",           "description": "Rs.200/pax"},
                    {"id": "act_bonfire",    "title": "Bonfire Evening",  "description": "Rs.300/group"},
                    {"id": "act_swimming",   "title": "Swimming (Pool)",  "description": "Rs.200/pax"},
                    {"id": "act_fruit_tour", "title": "Fruit Tour",       "description": "Rs.250/pax"},
                    {"id": "act_none",       "title": "No Activities",    "description": "Skip & continue"},
                ],
            },
        ],
    )
    _set_state(phone, "ASK_ACTIVITIES")


_ACTIVITY_MAP = {
    "act_veg_pick":    "Veg/Fruit Picking",
    "act_animal_pet":  "Animal Petting",
    "act_feed_animal": "Feeding Animals",
    "act_farm_tour":   "Guided Farm Tour",
    "act_kids_zone":   "Kids Activity Zone",
    "act_city_tour":   "City Tour",
    "act_kayaking":    "Kayaking",
    "act_beach":       "Beach Enjoy",
    "act_hiking":      "Hiking",
    "act_bonfire":     "Bonfire Evening",
    "act_swimming":    "Swimming (Pool)",
    "act_fruit_tour":  "Fruit Tour",
    "act_none":        None,
}


def _ask_activities(phone: str, content: str):
    s = _session(phone)
    if content == "act_none":
        s["activities"] = []
        _ask_pickup_step(phone)
        return

    activity = _ACTIVITY_MAP.get(content)
    if activity is None:
        whatsapp.send_text(phone, "Please select from the activity list.")
        return

    if activity not in s["activities"]:
        s["activities"].append(activity)

    chosen = ", ".join(s["activities"])
    whatsapp.send_buttons(
        phone,
        f"Added! Selected so far: *{chosen}*\n\nWould you like to add more activities?",
        [
            {"id": "act_more", "title": "Add More"},
            {"id": "act_done", "title": "Done"},
        ],
    )
    _set_state(phone, "ASK_ACTIVITIES_DONE")


def _ask_activities_done(phone: str, content: str):
    if content == "act_more":
        _ask_activities_step(phone)
    else:
        _ask_pickup_step(phone)


# ── Transport ─────────────────────────────────────────────────────────────────

def _ask_pickup_step(phone: str):
    s = _session(phone)
    # Self-drive guests don't need pickup
    if s.get("arrival_medium") == "Self-Drive":
        _s(phone, "transport", None)
        _ask_internal_transport_step(phone)
        return
    whatsapp.send_buttons(
        phone,
        "Do you need *pickup* from your arrival point to the farmhouse?",
        [
            {"id": "pickup_yes", "title": "Yes, Need Pickup"},
            {"id": "pickup_no",  "title": "No, Self-Arranged"},
        ],
    )
    _set_state(phone, "ASK_PICKUP")


def _ask_pickup(phone: str, content: str):
    if content == "pickup_yes":
        s = _session(phone)
        medium = s.get("arrival_medium", "")
        # Reorder rows to surface likely port first
        all_rows = [
            {"id": "port_kudal",   "title": "Kudal Station",     "description": f"Rs.{pricing.TRANSPORT['Kudal Station']:,}"},
            {"id": "port_kankaw",  "title": "Kankawali Station",  "description": f"Rs.{pricing.TRANSPORT['Kankawali Station']:,}"},
            {"id": "port_mopa",    "title": "Mopa Airport (GOX)", "description": f"Rs.{pricing.TRANSPORT['Mopa Airport (GOX)']:,}"},
            {"id": "port_dabolim", "title": "Dabolim Airport",    "description": f"Rs.{pricing.TRANSPORT['Goa Airport – Dabolim']:,}"},
        ]
        if "Mopa" in medium:
            all_rows = [all_rows[2]] + [r for r in all_rows if r["id"] != "port_mopa"]
        elif "Dabolim" in medium:
            all_rows = [all_rows[3]] + [r for r in all_rows if r["id"] != "port_dabolim"]

        whatsapp.send_list(
            phone, "Which point will you arrive at?", "Select Pickup Point",
            [{"title": "Pickup Locations", "rows": all_rows}],
        )
        _set_state(phone, "ASK_ARRIVAL_PORT")
    elif content == "pickup_no":
        _s(phone, "transport", None)
        _ask_internal_transport_step(phone)
    else:
        whatsapp.send_text(phone, "Please tap one of the options above.")


_PORT_MAP = {
    "port_kudal":   "Kudal Station",
    "port_kankaw":  "Kankawali Station",
    "port_mopa":    "Mopa Airport (GOX)",
    "port_dabolim": "Goa Airport – Dabolim",
}


def _ask_arrival_port(phone: str, content: str):
    port = _PORT_MAP.get(content)
    if not port:
        whatsapp.send_text(phone, "Please select your pickup point from the list.")
        return
    _s(phone, "transport", port)
    _ask_internal_transport_step(phone)


def _ask_internal_transport_step(phone: str):
    s = _session(phone)
    nights = s.get("nights", 1)
    whatsapp.send_list(
        phone,
        f"Do you need a *vehicle during your {nights}-night stay* for local travel?\n"
        "_(Fuel included within 50 km/day)_",
        "Select Vehicle",
        [{"title": "Local Transport (per day)", "rows": [
            {"id": "int_none",    "title": "No Vehicle Needed",  "description": "Self-managed / own transport"},
            {"id": "int_scooter", "title": "Scooter / 2-Wheeler","description": f"Rs.{pricing.INTERNAL_TRANSPORT['Scooter / 2-Wheeler']:,}/day"},
            {"id": "int_hatch",   "title": "Hatchback (4-seat)", "description": f"Rs.{pricing.INTERNAL_TRANSPORT['Hatchback (4-seater)']:,}/day"},
            {"id": "int_suv",     "title": "SUV (6-7 seat)",     "description": f"Rs.{pricing.INTERNAL_TRANSPORT['SUV (6–7 seater)']:,}/day"},
        ]}],
    )
    _set_state(phone, "ASK_INTERNAL_TRANSPORT")


_INT_TRANSPORT_MAP = {
    "int_none":    None,
    "int_scooter": "Scooter / 2-Wheeler",
    "int_hatch":   "Hatchback (4-seater)",
    "int_suv":     "SUV (6–7 seater)",
}


def _ask_internal_transport(phone: str, content: str):
    if content not in _INT_TRANSPORT_MAP:
        whatsapp.send_text(phone, "Please select a transport option from the list.")
        return
    _s(phone, "internal_transport", _INT_TRANSPORT_MAP[content])
    _ask_trip_planning_step(phone)


# ── Trip planning ─────────────────────────────────────────────────────────────

def _ask_trip_planning_step(phone: str):
    s = _session(phone)
    if s.get("nights", 1) >= 2:
        interest = s.get("interests", "")
        whatsapp.send_buttons(
            phone,
            f"Would you like *trip planning suggestions* tailored for *{interest}* in Goa? 🗺️",
            [
                {"id": "trip_yes", "title": "Yes Please!"},
                {"id": "trip_no",  "title": "No Thanks"},
            ],
        )
        _set_state(phone, "ASK_TRIP_PLANNING")
    else:
        _show_summary(phone)


def _ask_trip_planning(phone: str, content: str):
    if content == "trip_yes":
        s = _session(phone)
        _send_trip_suggestions(phone, s.get("interests", ""))
    _show_summary(phone)


_TRIP_SUGGESTIONS = {
    "Nature & Wildlife": (
        "🌿 *Nature & Wildlife — Top Spots*\n\n"
        "📍 Dudhsagar Falls — 45 km (iconic waterfall)\n"
        "📍 Bhagwan Mahaveer Wildlife Sanctuary — 35 km\n"
        "📍 Netravali Wildlife Sanctuary — 40 km\n"
        "📍 Cotigao Bird Sanctuary — 25 km\n"
        "📍 Bondla Mini Zoo — 50 km\n\n"
        "Best time for birdwatching: 6–9 AM\n"
        "Tip: Carry binoculars & wear earthy tones."
    ),
    "Beach & Water Sports": (
        "🏖️ *Beach & Water Sports — Top Spots*\n\n"
        "📍 Palolem Beach — 20 km (most scenic)\n"
        "📍 Agonda Beach — 18 km (quiet & clean)\n"
        "📍 Cola Beach — 22 km (private lagoon)\n"
        "📍 Butterfly Beach — 25 km (boat-access only)\n\n"
        "Activities: Kayaking, snorkelling, parasailing\n"
        "Tip: Avoid beaches on Tuesdays (cleaning day)."
    ),
    "Culture & Heritage": (
        "🏛️ *Culture & Heritage — Top Spots*\n\n"
        "📍 Basilica of Bom Jesus (UNESCO) — 60 km\n"
        "📍 Ancestral Goa Museum — 55 km\n"
        "📍 Savoi Spice Plantation — 45 km\n"
        "📍 Sahakari Spice Farm — 50 km\n"
        "📍 Goa State Museum, Panaji — 65 km\n\n"
        "Tip: Full-day culture tour recommended."
    ),
    "Holistic & Wellness": (
        "🧘 *Holistic & Wellness — What We Offer*\n\n"
        "🌅 Sunrise yoga on our farm lawn (on request)\n"
        "🌿 Organic farm-to-table meals by our cook\n"
        "🌊 Agonda Beach — sunrise meditation walks\n"
        "💆 Ayurvedic massage — arrange on premises\n"
        "🍃 Herbal teas & detox menu available\n\n"
        "Let us know to prepare a custom wellness schedule!"
    ),
    "Festival & Celebration": (
        "🎉 *Festival & Celebration — We Can Arrange*\n\n"
        "🔥 Bonfire with BBQ & music\n"
        "🎂 Birthday / anniversary cake\n"
        "🌺 Decorated room for special occasions\n"
        "📸 Farm photoshoot setup\n"
        "🥂 Celebration package — ask us!\n\n"
        f"📞 To discuss arrangements: {config.PROPERTY_CONTACT}"
    ),
    "Adventure & Outdoor": (
        "🏕️ *Adventure & Outdoor — Top Experiences*\n\n"
        "🥾 Guided trekking — Sahyadri foothills\n"
        "🚴 Cycling — farm roads & paddy trails\n"
        "🎣 Fishing — Talpona River (15 km)\n"
        "🛶 River rafting — Mhadei (seasonal)\n"
        "🏕️ Camping & stargazing on farm\n"
        "🧗 Rock climbing — Chandranath Hill"
    ),
    "Quiet Getaway": (
        "☮️ *Quiet Getaway — What to Enjoy Here*\n\n"
        "📚 Farm reading corner with hammocks\n"
        "🌅 Sunrise & sunset viewpoints on property\n"
        "🐦 Self-guided morning birdwalk (map provided)\n"
        "🌾 Leisurely farm & plantation walks\n"
        "🍵 Evening tea by the farm pond\n\n"
        "Our team ensures minimal noise & maximum peace. 🤫"
    ),
}


def _send_trip_suggestions(phone: str, interest: str):
    msg = _TRIP_SUGGESTIONS.get(
        interest,
        "🗺️ Our team will share a personalised itinerary after booking confirmation!",
    )
    whatsapp.send_text(phone, msg)
    whatsapp.send_text(
        phone,
        f"📞 *Contacts for Your Trip*\n\n"
        f"🚗 Driver: {config.TRANSPORT_CONTACT}\n"
        f"🎭 Tour Guide: {config.TOUR_GUIDE_CONTACT}\n"
        f"🏄 Sports / Adventure: {config.SPORTS_GUIDE_CONTACT}\n\n"
        "_Share your booking ID when you reach out._",
    )


# ── Summary & Confirmation ────────────────────────────────────────────────────

def _show_summary(phone: str):
    s = _session(phone)
    ci_month = date.fromisoformat(s["check_in"]).month

    totals = pricing.calculate_total(
        pax=s["pax"],
        rooms=s["rooms_count"],
        nights=s["nights"],
        room_type=s["room_type"],
        selected_activities=s["activities"],
        transport_port=s["transport"],
        meal_plan=s["meal_plan"],
        internal_transport=s["internal_transport"],
        check_in_month=ci_month,
    )

    # Activity lines
    act_lines = (
        "\n".join(
            f"  • {a}: Rs.{pricing.ACTIVITIES[a]:,}"
            + ("" if a in pricing.BONFIRE_PER_GROUP else f" x {s['pax']} pax")
            + f" = Rs.{pricing.ACTIVITIES[a] * (1 if a in pricing.BONFIRE_PER_GROUP else s['pax']):,}"
            for a in s["activities"]
        )
    ) if s["activities"] else "  None"

    transport_line = (
        f"  {s['transport']}: Rs.{pricing.TRANSPORT[s['transport']]:,}"
        if s["transport"] else "  None / Self-arranged"
    )

    int_trans_line = (
        f"  {s['internal_transport']}: Rs.{pricing.INTERNAL_TRANSPORT[s['internal_transport']]:,}/day x {s['nights']}n"
        if s["internal_transport"] else "  None"
    )

    meal_line = (
        f"  {s['meal_plan']}: Rs.{pricing.MEAL_PLAN[s['meal_plan']]:,}/pax/n x {s['pax']} pax x {s['nights']}n"
        if s["meal_plan"] != "No Meals" else "  No Meals"
    )

    summary = (
        f"*Booking Summary — {config.PROPERTY_NAME}*\n\n"
        f"*Guest:* {s.get('guest_name', '—')}\n"
        f"*Group:* {s.get('client_type', '—')}\n"
        f"*Interest:* {s.get('interests', '—')}\n"
        f"*Arrival:* {s.get('arrival_medium', '—')}\n\n"
        f"*Dates:* {s['check_in']} to {s['check_out']} ({s['nights']} night(s))\n"
        f"*Guests:* {s['pax']}   *Rooms:* {s['rooms_count']} ({s['room_type']})\n"
        f"*Food:* {s.get('food_preferences', '—')}\n\n"
        f"*Room Cost:* Rs.{totals['room']:,}  _{totals['seasonal_note']}_\n\n"
        f"*Meals* ({s['meal_plan']}):\n{meal_line}\n"
        f"  Subtotal: Rs.{totals['meals']:,}\n\n"
        f"*Activities:*\n{act_lines}\n"
        f"  Subtotal: Rs.{totals['activities']:,}\n\n"
        f"*Pickup:*\n{transport_line}\n\n"
        f"*Local Transport:*\n{int_trans_line}\n"
        f"  Subtotal: Rs.{totals['internal_transport']:,}\n\n"
        f"{'—' * 20}\n"
        f"*TOTAL: Rs.{totals['total']:,}*\n"
        f"{'—' * 20}\n\n"
        "Shall I confirm this booking?"
    )

    SESSIONS[phone]["_totals"] = totals
    whatsapp.send_buttons(
        phone, summary,
        [
            {"id": "confirm_yes", "title": "Confirm Booking"},
            {"id": "confirm_no",  "title": "Cancel"},
        ],
    )
    _set_state(phone, "CONFIRM_BOOKING")


def _confirm_booking(phone: str, content: str):
    if content == "confirm_no":
        whatsapp.send_text(phone, "Booking cancelled. Type *Hi* anytime to start again! 🌿")
        del SESSIONS[phone]
        return
    if content != "confirm_yes":
        whatsapp.send_text(phone, "Please tap Confirm Booking or Cancel.")
        return

    s = _session(phone)
    totals = s.get("_totals") or {}

    booking_id = database.create_booking(
        phone=phone,
        check_in=s["check_in"],
        check_out=s["check_out"],
        room_type=s["room_type"],
        rooms_count=s["rooms_count"],
        pax=s["pax"],
        activities=s["activities"],
        transport=s["transport"],
        total_amount=totals.get("total", 0),
        guest_name=s.get("guest_name"),
        client_type=s.get("client_type"),
        interests=s.get("interests"),
        arrival_medium=s.get("arrival_medium"),
        food_preferences=s.get("food_preferences"),
        meal_plan=s.get("meal_plan", "No Meals"),
        meal_location=s.get("meal_location", "In-house"),
        internal_transport=s.get("internal_transport"),
    )

    # 1. Confirmation + payment
    whatsapp.send_text(
        phone,
        f"*Booking Confirmed!* 🎉\n\n"
        f"*Booking ID:* #{booking_id}\n"
        f"*Name:* {s.get('guest_name', '—')}\n"
        f"*Dates:* {s['check_in']} to {s['check_out']}\n"
        f"*Total:* Rs.{totals.get('total', 0):,}\n\n"
        f"{config.PAYMENT_INFO}",
    )

    # 2. Farmhouse address & check-in details
    whatsapp.send_text(
        phone,
        f"*Farmhouse Details*\n\n"
        f"*Address:* {config.PROPERTY_ADDRESS}\n"
        f"*GPS / Maps:* {config.PROPERTY_GPS}\n\n"
        f"*Check-in:*  {config.CHECK_IN_TIME}\n"
        f"*Check-out:* {config.CHECK_OUT_TIME}\n\n"
        f"*Contact:* {config.PROPERTY_CONTACT}\n"
        f"_Please carry a valid Govt. Photo ID._",
    )

    # 3. Things to carry + climate
    ci_month = date.fromisoformat(s["check_in"]).month
    climate  = config.CLIMATE_BY_MONTH.get(ci_month, "Expect warm, pleasant weather.")
    whatsapp.send_text(
        phone,
        "*What to Carry*\n\n"
        + "\n".join(config.THINGS_TO_CARRY)
        + f"\n\n*Climate during your stay:*\n{climate}",
    )

    # 4. Medical & emergency
    whatsapp.send_text(
        phone,
        f"*Medical & Emergency*\n\n"
        f"Nearest Hospital: {config.NEAREST_HOSPITAL}\n"
        f"Hospital Contact: {config.MEDICAL_CONTACT}\n"
        f"Ambulance: {config.AMBULANCE}\n"
        f"{config.PHARMACY_INFO}",
    )

    # 5. Transport contacts (only if relevant)
    if s.get("transport") or s.get("internal_transport"):
        whatsapp.send_text(
            phone,
            f"*Transport Contacts*\n\n"
            f"Driver: {config.TRANSPORT_CONTACT}\n"
            f"Tour Guide: {config.TOUR_GUIDE_CONTACT}\n"
            f"Adventure / Sports: {config.SPORTS_GUIDE_CONTACT}\n\n"
            f"_Please share booking ID *#{booking_id}* when contacting them._",
        )

    # 6. Relevant policies based on client type
    ct  = s.get("client_type", "")
    pol = f"*Property Policies*\n\n" \
          f"Noise: {config.NOISE_POLICY}\n" \
          f"Pets:  {config.PET_POLICY}"
    if "Family" in ct:
        pol += f"\nKids:  {config.CHILD_POLICY}"
    if "Wellness" in ct or "Senior" in ct:
        pol += f"\nSeniors: {config.SENIOR_POLICY}"
    pol += f"\nDisabled Access: {config.DISABLED_POLICY}"
    whatsapp.send_text(phone, pol)

    # 7. Farewell
    whatsapp.send_text(
        phone,
        f"Thank you for choosing *{config.PROPERTY_NAME}*! 🌿\n"
        "We look forward to hosting you. See you soon! 🙏\n\n"
        "Type *Hi* anytime to make another booking.",
    )

    del SESSIONS[phone]


# ═══════════════════════════════════════════════════════════════════════════════
# ── INFO BRANCH ───────────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

def _show_info_menu(phone: str):
    whatsapp.send_list(
        phone,
        f"*{config.PROPERTY_NAME} — Property Information*\n\nWhat would you like to know?",
        "Browse Info",
        [
            {
                "title": "Property",
                "rows": [
                    {"id": "info_facilities", "title": "Facilities",        "description": "TV, AC, WiFi, pool, power..."},
                    {"id": "info_rooms",      "title": "Rooms & Bathrooms", "description": "Room types, bathroom details"},
                    {"id": "info_policies",   "title": "Policies",          "description": "Check-in/out, noise, pets, kids"},
                    {"id": "info_payments",   "title": "Payments",          "description": "UPI, cards, cash options"},
                ],
            },
            {
                "title": "Activities & Logistics",
                "rows": [
                    {"id": "info_activities", "title": "Activities & Games", "description": "Farm, adventure, free games"},
                    {"id": "info_transport",  "title": "Transport",          "description": "Pickup, drivers, guides"},
                    {"id": "info_medical",    "title": "Medical / Emergency","description": "Hospital, pharmacy"},
                    {"id": "info_carry",      "title": "What to Carry",      "description": "Packing tips & checklist"},
                    {"id": "info_climate",    "title": "Climate & Weather",  "description": "Seasonal guide"},
                    {"id": "info_photos",     "title": "Photos",             "description": "How to view farm photos"},
                ],
            },
        ],
    )
    _set_state(phone, "INFO_MENU")


def _info_menu(phone: str, content: str):
    dispatch = {
        "info_facilities": _info_facilities,
        "info_rooms":      _info_rooms,
        "info_policies":   _info_policies,
        "info_payments":   _info_payments,
        "info_activities": _info_activities,
        "info_transport":  _info_transport,
        "info_medical":    _info_medical,
        "info_carry":      _info_carry,
        "info_climate":    _info_climate,
        "info_photos":     _info_photos,
    }
    handler = dispatch.get(content)
    if handler:
        handler(phone)
    else:
        whatsapp.send_text(phone, "Please select a category from the menu.")


def _info_back_buttons(phone: str):
    whatsapp.send_buttons(
        phone,
        "What would you like to do next?",
        [
            {"id": "info_back", "title": "Back to Info Menu"},
            {"id": "main_book", "title": "Book a Stay"},
        ],
    )
    _set_state(phone, "INFO_BACK")


def _info_back(phone: str, content: str):
    if content == "info_back":
        _show_info_menu(phone)
    elif content == "main_book":
        name = _session(phone).get("guest_name")
        if name:
            whatsapp.send_text(
                phone,
                f"Welcome back, *{name}*! 😊\n\n"
                "Please share your *check-in and check-out dates*:\n"
                "Example: _4 June 2026 to 6 June 2026_",
            )
            _set_state(phone, "ASK_DATES")
        else:
            whatsapp.send_text(phone, "Let's get started! What is your *name*?")
            _set_state(phone, "ASK_NAME")
    else:
        _show_info_menu(phone)


# ── Info handlers ─────────────────────────────────────────────────────────────

def _info_facilities(phone: str):
    lines = "\n".join(f"  {k}: {v}" for k, v in config.FACILITIES.items())
    whatsapp.send_text(phone, f"*Facilities at {config.PROPERTY_NAME}*\n\n{lines}")
    _info_back_buttons(phone)


def _info_rooms(phone: str):
    text = ""
    for r in config.ROOM_DETAILS:
        ac  = "AC" if r["ac"]  else "No AC"
        tv  = "TV" if r["tv"]  else "No TV"
        text += (
            f"*{r['name']} — {r['type']}*\n"
            f"  Bathroom: {r['bathroom']}\n"
            f"  {ac}  |  {tv}  |  Max {r['pax']} guests\n"
            f"  Base Rate: Rs.{r['rate']:,}/night\n\n"
        )
    whatsapp.send_text(phone, f"*Room Details*\n\n{text.strip()}")
    _info_back_buttons(phone)


def _info_policies(phone: str):
    msg = (
        f"*Property Policies*\n\n"
        f"Check-in:  {config.CHECK_IN_TIME}\n"
        f"Check-out: {config.CHECK_OUT_TIME}\n\n"
        f"Noise Policy:\n{config.NOISE_POLICY}\n\n"
        f"Pets:\n{config.PET_POLICY}\n\n"
        f"Children:\n{config.CHILD_POLICY}\n\n"
        f"Senior Citizens:\n{config.SENIOR_POLICY}\n\n"
        f"Differently Abled:\n{config.DISABLED_POLICY}\n\n"
        f"Extra Guest: Rs.{config.EXTRA_PERSON_FEE}/person/night (above 3 per room)"
    )
    whatsapp.send_text(phone, msg)
    _info_back_buttons(phone)


def _info_payments(phone: str):
    whatsapp.send_text(phone, config.PAYMENT_INFO)
    _info_back_buttons(phone)


def _info_activities(phone: str):
    paid = "\n".join(f"  {k}: Rs.{v:,}/pax" for k, v in pricing.ACTIVITIES.items())
    free = "  " + "  |  ".join(pricing.GAMES_FREE)
    whatsapp.send_text(
        phone,
        f"*Activities & Games at {config.PROPERTY_NAME}*\n\n"
        f"*Paid Activities:*\n{paid}\n"
        f"_(Bonfire Evening is per group, not per pax)_\n\n"
        f"*Free Games (complimentary):*\n{free}\n\n"
        "_Activities subject to availability & season._",
    )
    _info_back_buttons(phone)


def _info_transport(phone: str):
    pickup = "\n".join(f"  {k}: Rs.{v:,}" for k, v in pricing.TRANSPORT.items())
    local  = "\n".join(f"  {k}: Rs.{v:,}/day" for k, v in pricing.INTERNAL_TRANSPORT.items())
    whatsapp.send_text(
        phone,
        f"*Transport Options*\n\n"
        f"*Pickup from Station / Airport:*\n{pickup}\n\n"
        f"*Local Vehicle during Stay:*\n{local}\n\n"
        f"*Contacts:*\n"
        f"  Driver: {config.TRANSPORT_CONTACT}\n"
        f"  Tour Guide: {config.TOUR_GUIDE_CONTACT}\n"
        f"  Sports / Adventure: {config.SPORTS_GUIDE_CONTACT}",
    )
    _info_back_buttons(phone)


def _info_medical(phone: str):
    whatsapp.send_text(
        phone,
        f"*Medical & Emergency Information*\n\n"
        f"Nearest Hospital: {config.NEAREST_HOSPITAL}\n"
        f"Hospital Contact: {config.MEDICAL_CONTACT}\n"
        f"Ambulance (free): {config.AMBULANCE}\n"
        f"{config.PHARMACY_INFO}\n\n"
        f"Basic first-aid kit available at reception.\n"
        f"Our caretaker is available 24/7 for emergencies.",
    )
    _info_back_buttons(phone)


def _info_carry(phone: str):
    items = "\n".join(config.THINGS_TO_CARRY)
    whatsapp.send_text(phone, f"*What to Carry — Packing Checklist*\n\n{items}")
    _info_back_buttons(phone)


def _info_climate(phone: str):
    month = date.today().month
    current = config.CLIMATE_BY_MONTH.get(month, "Expect warm, pleasant weather.")
    # Show next 3 months
    upcoming = ""
    for offset in range(1, 4):
        m = (month - 1 + offset) % 12 + 1
        from datetime import date as _d
        month_name = _d(2024, m, 1).strftime("%B")
        upcoming += f"  *{month_name}:* {config.CLIMATE_BY_MONTH.get(m, '')}\n"
    whatsapp.send_text(
        phone,
        f"*Climate Guide — {config.PROPERTY_NAME}*\n\n"
        f"*This Month:* {current}\n\n"
        f"*Coming Months:*\n{upcoming}\n"
        "Type your travel month for a specific forecast!",
    )
    _info_back_buttons(phone)


def _info_photos(phone: str):
    whatsapp.send_text(
        phone,
        f"*Farm Photos & Virtual Tour*\n\n"
        "We'd love to share our photo gallery with you!\n\n"
        f"Contact us directly:\n"
        f"  {config.PROPERTY_CONTACT}\n\n"
        "We'll send you photos of:\n"
        "  Rooms & bathrooms\n"
        "  Farm, gardens & orchards\n"
        "  Dining area & outdoor spaces\n"
        "  Pool & activity areas\n"
        "  Sunrise / sunset views\n\n"
        "_We're also on Google Maps — search for our property for guest photos._",
    )
    _info_back_buttons(phone)


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN DISPATCHER
# ═══════════════════════════════════════════════════════════════════════════════

_HANDLERS = {
    "MAIN_MENU":              _main_menu,
    "ASK_NAME":               _ask_name,
    "ASK_CLIENT_TYPE":        _ask_client_type,
    "ASK_INTERESTS":          _ask_interests,
    "ASK_ARRIVAL_MEDIUM":     _ask_arrival_medium,
    "ASK_DATES":              _ask_dates,
    "ASK_ROOM_TYPE":          _ask_room_type,
    "ASK_ROOM_COUNT":         _ask_room_count,
    "ASK_GUESTS":             _ask_guests,
    "AVAILABILITY_RETRY":     _availability_retry,
    "ASK_FOOD_PREFS":         _ask_food_prefs,
    "ASK_MEAL_PLAN":          _ask_meal_plan,
    "ASK_MEAL_LOCATION":      _ask_meal_location,
    "ASK_ACTIVITIES":         _ask_activities,
    "ASK_ACTIVITIES_DONE":    _ask_activities_done,
    "ASK_PICKUP":             _ask_pickup,
    "ASK_ARRIVAL_PORT":       _ask_arrival_port,
    "ASK_INTERNAL_TRANSPORT": _ask_internal_transport,
    "ASK_TRIP_PLANNING":      _ask_trip_planning,
    "CONFIRM_BOOKING":        _confirm_booking,
    "INFO_MENU":              _info_menu,
    "INFO_BACK":              _info_back,
}

_RESET_WORDS  = {"hi", "hello", "hey", "start", "restart"}
_INFO_WORDS   = {"info", "information", "details", "property", "rooms",
                 "facilities", "photos", "pictures", "policies", "rates",
                 "price", "pricing", "activities", "transport"}
_BOOK_WORDS   = {"book", "booking", "reserve", "reservation"}


def handle_message(phone: str, msg_type: str, content: str):
    content_lower = content.lower().strip()

    # Reset on greeting
    if content_lower in _RESET_WORDS:
        SESSIONS.pop(phone, None)

    s     = _session(phone)
    state = s["state"]

    # Always show welcome on WELCOME state
    if state == "WELCOME":
        _welcome(phone)
        return

    # Global keyword shortcuts
    if content_lower in _INFO_WORDS:
        _show_info_menu(phone)
        return

    if content_lower in _BOOK_WORDS:
        if s.get("guest_name"):
            whatsapp.send_text(
                phone,
                f"Welcome back, *{s['guest_name']}*! 😊\n\n"
                "Please share your *check-in and check-out dates*:\n"
                "Example: _4 June 2026 to 6 June 2026_",
            )
            _set_state(phone, "ASK_DATES")
        else:
            whatsapp.send_text(phone, "Let's get started! What is your *name*?")
            _set_state(phone, "ASK_NAME")
        return

    # Route to state handler
    handler = _HANDLERS.get(state)
    if handler:
        handler(phone, content)
    else:
        whatsapp.send_text(
            phone,
            "Type *Hi* to start a new booking or *Info* to browse property details.",
        )
