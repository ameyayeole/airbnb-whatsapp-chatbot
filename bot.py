import re
from datetime import datetime, date
import whatsapp
import database
import pricing
import config

# ── session store ──────────────────────────────────────────────────────────────
SESSIONS: dict[str, dict] = {}

STATES = (
    "WELCOME",
    "ASK_DATES",
    "ASK_GUESTS",
    "ASK_ROOM_TYPE",
    "ASK_ROOM_COUNT",
    "CHECK_AVAILABILITY",
    "ASK_ACTIVITIES",
    "ASK_TRANSPORT",
    "ASK_ARRIVAL_PORT",
    "SHOW_SUMMARY",
    "CONFIRM_BOOKING",
    "EXIT",
)

ACTIVITY_IDS = {
    "act_city_tour":   "City Tour",
    "act_kayaking":    "Kayaking",
    "act_beach_enjoy": "Beach Enjoy",
    "act_hiking":      "Hiking",
    "act_fruit_tour":  "Fruit Tour",
    "act_none":        None,
}

PORT_IDS = {
    "port_kudal":    "Kudal",
    "port_kankawali": "Kankawali",
    "port_mopa":     "Mopa Airport",
}


def _session(phone: str) -> dict:
    if phone not in SESSIONS:
        SESSIONS[phone] = {
            "state": "WELCOME",
            "check_in": None,
            "check_out": None,
            "nights": None,
            "pax": None,
            "room_type": None,
            "rooms_count": 1,
            "activities": [],
            "transport": False,
            "arrival_port": None,
        }
    return SESSIONS[phone]


def _set_state(phone: str, state: str):
    SESSIONS[phone]["state"] = state


# ── date parsing ───────────────────────────────────────────────────────────────

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}


def _parse_date_range(text: str):
    """
    Parse strings like:
      "4 June to 6 June"   "4-6 June"   "4th June to 6th June"
      "04/06 to 06/06"     "4 Jun - 6 Jun"
    Returns (check_in: date, check_out: date, nights: int) or None.
    """
    text = text.lower().strip()
    year = date.today().year

    # try DD/MM to DD/MM
    m = re.match(r"(\d{1,2})[/\-](\d{1,2})\s*(?:to|[-–])\s*(\d{1,2})[/\-](\d{1,2})", text)
    if m:
        d1, mo1, d2, mo2 = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
        ci = date(year, mo1, d1)
        co = date(year, mo2, d2)
        if co <= ci:
            co = co.replace(year=year + 1)
        return ci, co, (co - ci).days

    # try "4 June to 6 June" / "4-6 June"
    month_pattern = "|".join(sorted(_MONTHS.keys(), key=len, reverse=True))
    m = re.match(
        rf"(\d{{1,2}})\w*\s+({month_pattern})\s*(?:to|[-–])\s*(\d{{1,2}})\w*\s+({month_pattern})",
        text,
    )
    if m:
        d1, mo1, d2, mo2 = int(m.group(1)), _MONTHS[m.group(2)], int(m.group(3)), _MONTHS[m.group(4)]
        ci = date(year, mo1, d1)
        co = date(year, mo2, d2)
        if co <= ci:
            co = co.replace(year=year + 1)
        return ci, co, (co - ci).days

    # try "4-6 June" (same month)
    m = re.match(rf"(\d{{1,2}})\w*\s*[-–]\s*(\d{{1,2}})\w*\s+({month_pattern})", text)
    if m:
        d1, d2, mo = int(m.group(1)), int(m.group(2)), _MONTHS[m.group(3)]
        ci = date(year, mo, d1)
        co = date(year, mo, d2)
        if co <= ci:
            co = co.replace(year=year + 1)
        return ci, co, (co - ci).days

    return None


# ── state handlers ─────────────────────────────────────────────────────────────

def _welcome(phone: str):
    whatsapp.send_text(
        phone,
        "Welcome to *Farmhouse Goa* 🌿\n\n"
        "I'm here to help you book a stay, add activities, and arrange transport.\n\n"
        "Please share your preferred *check-in and check-out dates*.\n"
        "Example: _4 June to 6 June_",
    )
    _set_state(phone, "ASK_DATES")


def _ask_dates(phone: str, content: str):
    result = _parse_date_range(content)
    if not result:
        whatsapp.send_text(
            phone,
            "Sorry, I couldn't understand those dates. Please try again.\n"
            "Example: _4 June to 6 June_ or _4-6 June_",
        )
        return

    ci, co, nights = result
    if nights <= 0:
        whatsapp.send_text(phone, "Check-out must be after check-in. Please try again.")
        return

    s = _session(phone)
    s["check_in"] = ci.isoformat()
    s["check_out"] = co.isoformat()
    s["nights"] = nights

    whatsapp.send_text(
        phone,
        f"Got it! *{ci.strftime('%d %b')} → {co.strftime('%d %b')}* ({nights} night{'s' if nights > 1 else ''}).\n\n"
        "How many guests will be staying? (Enter a number)",
    )
    _set_state(phone, "ASK_GUESTS")


def _ask_guests(phone: str, content: str):
    if not content.isdigit() or int(content) < 1:
        whatsapp.send_text(phone, "Please enter a valid number of guests (e.g. 2).")
        return

    _session(phone)["pax"] = int(content)
    whatsapp.send_buttons(
        phone,
        "What type of booking are you looking for?",
        [
            {"id": "room_couple", "title": "Couple Room"},
            {"id": "room_bulk",   "title": "Bulk Booking"},
        ],
    )
    _set_state(phone, "ASK_ROOM_TYPE")


def _ask_room_type(phone: str, content: str):
    if content == "room_couple":
        s = _session(phone)
        s["room_type"] = "couple"
        s["rooms_count"] = 1
        _check_and_show_availability(phone)
    elif content == "room_bulk":
        _session(phone)["room_type"] = "bulk"
        whatsapp.send_buttons(
            phone,
            "How many rooms do you need? (We have 4 rooms total)",
            [
                {"id": "rooms_1", "title": "1 Room"},
                {"id": "rooms_2", "title": "2 Rooms"},
                {"id": "rooms_3", "title": "3 Rooms"},
            ],
        )
        _set_state(phone, "ASK_ROOM_COUNT")
    else:
        whatsapp.send_text(phone, "Please select an option from the buttons above.")


def _ask_room_count(phone: str, content: str):
    room_map = {"rooms_1": 1, "rooms_2": 2, "rooms_3": 3}
    if content == "rooms_4":
        _session(phone)["rooms_count"] = 4
        _check_and_show_availability(phone)
        return

    count = room_map.get(content)
    if count is None:
        whatsapp.send_text(phone, "Please select the number of rooms using the buttons.")
        return

    # If 3 was selected, offer 4 as well via a follow-up button
    if content == "rooms_3":
        whatsapp.send_buttons(
            phone,
            "Do you need 3 or 4 rooms?",
            [
                {"id": "rooms_3", "title": "3 Rooms"},
                {"id": "rooms_4", "title": "4 Rooms (All)"},
            ],
        )
        return

    _session(phone)["rooms_count"] = count
    _check_and_show_availability(phone)


def _check_and_show_availability(phone: str):
    s = _session(phone)
    available = database.check_availability(s["check_in"], s["check_out"], s["rooms_count"])

    if not available:
        whatsapp.send_text(
            phone,
            f"Sorry, we don't have *{s['rooms_count']} room(s)* available for "
            f"*{s['check_in']} to {s['check_out']}*.\n\n"
            "Please try different dates or fewer rooms. Type your dates to start again.",
        )
        _set_state(phone, "ASK_DATES")
        return

    nights = s["nights"]
    rooms = s["rooms_count"]
    if s["room_type"] == "couple":
        room_cost = pricing.ROOM_PRICE_COUPLE * nights
        price_line = f"₹{pricing.ROOM_PRICE_COUPLE:,}/night × {nights} night(s) = ₹{room_cost:,}"
    else:
        room_cost = pricing.ROOM_PRICE_BULK * rooms * nights
        price_line = (
            f"₹{pricing.ROOM_PRICE_BULK:,}/room/night × {rooms} room(s) × {nights} night(s) = ₹{room_cost:,}"
        )

    whatsapp.send_list(
        phone,
        f"Great news! Rooms are *available* ✅\n\n"
        f"*Room cost:* {price_line}\n\n"
        "Would you like to add any activities? Select all that apply and tap *Done*.",
        "Select Activities",
        [
            {
                "title": "Activities",
                "rows": [
                    {"id": "act_city_tour",   "title": "City Tour",   "description": f"₹{pricing.ACTIVITIES['City Tour']}/pax"},
                    {"id": "act_kayaking",    "title": "Kayaking",    "description": f"₹{pricing.ACTIVITIES['Kayaking']}/pax"},
                    {"id": "act_beach_enjoy", "title": "Beach Enjoy", "description": f"₹{pricing.ACTIVITIES['Beach Enjoy']}/pax"},
                    {"id": "act_hiking",      "title": "Hiking",      "description": f"₹{pricing.ACTIVITIES['Hiking']}/pax"},
                    {"id": "act_fruit_tour",  "title": "Fruit Tour",  "description": f"₹{pricing.ACTIVITIES['Fruit Tour']}/pax"},
                    {"id": "act_none",        "title": "No Activities", "description": "Skip activities"},
                ],
            }
        ],
    )
    _set_state(phone, "ASK_ACTIVITIES")


def _ask_activities(phone: str, content: str):
    s = _session(phone)

    if content == "act_none":
        s["activities"] = []
    else:
        activity_name = ACTIVITY_IDS.get(content)
        if activity_name and activity_name not in s["activities"]:
            s["activities"].append(activity_name)

        # Ask if they want to add more or continue
        chosen = ", ".join(s["activities"]) if s["activities"] else "None"
        whatsapp.send_buttons(
            phone,
            f"Added! Selected so far: *{chosen}*\n\nWould you like to add more activities or continue?",
            [
                {"id": "act_more",     "title": "Add More"},
                {"id": "act_done",     "title": "Done"},
            ],
        )
        _set_state(phone, "ASK_ACTIVITIES_DONE")
        return

    _ask_transport_step(phone)


def _ask_activities_done(phone: str, content: str):
    if content == "act_more":
        s = _session(phone)
        chosen = ", ".join(s["activities"]) if s["activities"] else "None"
        whatsapp.send_list(
            phone,
            f"Currently selected: *{chosen}*\n\nPick another activity:",
            "Select Activity",
            [
                {
                    "title": "Activities",
                    "rows": [
                        {"id": "act_city_tour",   "title": "City Tour",   "description": f"₹{pricing.ACTIVITIES['City Tour']}/pax"},
                        {"id": "act_kayaking",    "title": "Kayaking",    "description": f"₹{pricing.ACTIVITIES['Kayaking']}/pax"},
                        {"id": "act_beach_enjoy", "title": "Beach Enjoy", "description": f"₹{pricing.ACTIVITIES['Beach Enjoy']}/pax"},
                        {"id": "act_hiking",      "title": "Hiking",      "description": f"₹{pricing.ACTIVITIES['Hiking']}/pax"},
                        {"id": "act_fruit_tour",  "title": "Fruit Tour",  "description": f"₹{pricing.ACTIVITIES['Fruit Tour']}/pax"},
                    ],
                }
            ],
        )
        _set_state(phone, "ASK_ACTIVITIES")
    else:
        _ask_transport_step(phone)


def _ask_transport_step(phone: str):
    whatsapp.send_buttons(
        phone,
        "Do you need transport from your arrival point to the farmhouse?",
        [
            {"id": "transport_yes", "title": "Yes, need transport"},
            {"id": "transport_no",  "title": "No transport"},
        ],
    )
    _set_state(phone, "ASK_TRANSPORT")


def _ask_transport(phone: str, content: str):
    if content == "transport_yes":
        _session(phone)["transport"] = True
        whatsapp.send_buttons(
            phone,
            "Which port/station will you arrive at?",
            [
                {"id": "port_kudal",     "title": "Kudal"},
                {"id": "port_kankawali", "title": "Kankawali"},
                {"id": "port_mopa",      "title": "Mopa Airport"},
            ],
        )
        _set_state(phone, "ASK_ARRIVAL_PORT")
    elif content == "transport_no":
        _session(phone)["transport"] = False
        _show_summary(phone)
    else:
        whatsapp.send_text(phone, "Please choose one of the options above.")


def _ask_arrival_port(phone: str, content: str):
    port_name = PORT_IDS.get(content)
    if not port_name:
        whatsapp.send_text(phone, "Please select your arrival point using the buttons.")
        return
    _session(phone)["arrival_port"] = port_name
    _show_summary(phone)


def _show_summary(phone: str):
    s = _session(phone)
    totals = pricing.calculate_total(
        pax=s["pax"],
        rooms=s["rooms_count"],
        nights=s["nights"],
        selected_activities=s["activities"],
        transport_port=s["arrival_port"],
    )

    activities_line = (
        "  • " + "\n  • ".join(
            f"{a}: ₹{pricing.ACTIVITIES[a]:,} × {s['pax']} pax = ₹{pricing.ACTIVITIES[a] * s['pax']:,}"
            for a in s["activities"]
        )
        if s["activities"] else "  None"
    )

    transport_line = (
        f"  {s['arrival_port']}: ₹{pricing.TRANSPORT[s['arrival_port']]:,}"
        if s["arrival_port"] else "  None"
    )

    summary = (
        f"*📋 Booking Summary*\n\n"
        f"*Dates:* {s['check_in']} → {s['check_out']} ({s['nights']} night(s))\n"
        f"*Guests:* {s['pax']} pax\n"
        f"*Room type:* {s['room_type'].capitalize()} ({s['rooms_count']} room(s))\n\n"
        f"*Room cost:* ₹{totals['room']:,}\n\n"
        f"*Activities:*\n{activities_line}\n"
        f"  Subtotal: ₹{totals['activities']:,}\n\n"
        f"*Transport:*\n{transport_line}\n"
        f"  Subtotal: ₹{totals['transport']:,}\n\n"
        f"━━━━━━━━━━━━━━━\n"
        f"*Total: ₹{totals['total']:,}*\n"
        f"━━━━━━━━━━━━━━━\n\n"
        "Would you like to *confirm* this booking?"
    )

    SESSIONS[phone]["_totals"] = totals
    whatsapp.send_buttons(
        phone,
        summary,
        [
            {"id": "confirm_yes", "title": "Confirm Booking"},
            {"id": "confirm_no",  "title": "Cancel"},
        ],
    )
    _set_state(phone, "CONFIRM_BOOKING")


def _confirm_booking(phone: str, content: str):
    if content == "confirm_no":
        whatsapp.send_text(phone, "Booking cancelled. Feel free to start again anytime by saying *Hi*!")
        del SESSIONS[phone]
        return

    if content != "confirm_yes":
        whatsapp.send_text(phone, "Please tap Confirm Booking or Cancel.")
        return

    s = _session(phone)
    totals = s.get("_totals", {})

    booking_id = database.create_booking(
        phone=phone,
        check_in=s["check_in"],
        check_out=s["check_out"],
        room_type=s["room_type"],
        rooms_count=s["rooms_count"],
        pax=s["pax"],
        activities=s["activities"],
        transport=s["arrival_port"],
        total_amount=totals.get("total", 0),
    )

    whatsapp.send_text(
        phone,
        f"*Booking Confirmed!* 🎉\n\n"
        f"Your booking ID is *#{booking_id}*.\n\n"
        f"*Total Amount:* ₹{totals.get('total', 0):,}\n"
        "Please complete payment via UPI/QR to confirm your slot.\n\n"
        "We'll send a confirmation once payment is received.",
    )

    if s["arrival_port"]:
        whatsapp.send_text(
            phone,
            f"*Transport Details* 🚗\n\n"
            f"Pickup from: *{s['arrival_port']}*\n\n"
            f"Transport Agency Contact:\n{config.TRANSPORT_CONTACT}\n\n"
            "Please share your booking ID with them when you reach out.",
        )

    whatsapp.send_text(
        phone,
        "Thank you for choosing *Farmhouse Goa*! 🌴\n"
        "Looking forward to hosting you. Type *Hi* anytime to make another booking.",
    )

    del SESSIONS[phone]


# ── main dispatcher ────────────────────────────────────────────────────────────

_HANDLERS = {
    "WELCOME":             lambda phone, _content: _welcome(phone),
    "ASK_DATES":           _ask_dates,
    "ASK_GUESTS":          _ask_guests,
    "ASK_ROOM_TYPE":       _ask_room_type,
    "ASK_ROOM_COUNT":      _ask_room_count,
    "ASK_ACTIVITIES":      _ask_activities,
    "ASK_ACTIVITIES_DONE": _ask_activities_done,
    "ASK_TRANSPORT":       _ask_transport,
    "ASK_ARRIVAL_PORT":    _ask_arrival_port,
    "CONFIRM_BOOKING":     _confirm_booking,
}


def handle_message(phone: str, msg_type: str, content: str):
    # "hi" / "hello" resets session
    if content.lower() in ("hi", "hello", "hey", "start"):
        SESSIONS.pop(phone, None)

    s = _session(phone)
    state = s["state"]

    if state == "WELCOME":
        _welcome(phone)
        return

    handler = _HANDLERS.get(state)
    if handler:
        handler(phone, content)
    else:
        whatsapp.send_text(phone, "Type *Hi* to start a new booking.")
