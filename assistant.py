"""
assistant.py — front-desk dashboard for the hotel assistant.

Separate password (ASSISTANT_PASSWORD) and its own session flag, so signing in
here never grants access to the owner admin. Bookings are otherwise read-only
here, except for two actions the person physically at the desk needs: the
walk-in form (confirms a booking for a guest who arrived without booking
online) and recording a payment (cash/UPI/card handed over at the desk —
e.g. the remaining balance at check-in). Both of those same two actions are
also exposed from the owner admin, sharing this exact same code, so the two
dashboards can never behave differently or drift out of sync.
"""
import hmac
import json
import re
from datetime import date, datetime, timedelta
from functools import wraps
from zoneinfo import ZoneInfo

from flask import (
    Blueprint, render_template, request, redirect, url_for, session, flash, abort,
)

import config
import database
import pricing

assistant_bp = Blueprint("assistant", __name__, url_prefix="/assistant")

IST = ZoneInfo("Asia/Kolkata")


# ─── auth ────────────────────────────────────────────────────────────────────

def _is_allowed() -> bool:
    # The owner can also view this desk, but an assistant session cannot reach /admin.
    return bool(session.get("assistant") or session.get("admin"))


def assistant_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not _is_allowed():
            return redirect(url_for("assistant.login_page", next=request.path))
        return fn(*args, **kwargs)
    return wrapper


@assistant_bp.get("/login")
def login_page():
    return render_template("assistant/login.html", error=None)


@assistant_bp.post("/login")
def login():
    if not config.ASSISTANT_PASSWORD:
        return render_template(
            "assistant/login.html",
            error="Assistant access isn't set up yet. The owner needs to set ASSISTANT_PASSWORD.",
        ), 503
    pw = (request.form.get("password") or "").strip()
    if pw and hmac.compare_digest(pw, config.ASSISTANT_PASSWORD):
        session["assistant"] = True
        # Only follow `next` to a page inside the desk, never to another site.
        nxt = request.args.get("next") or ""
        if not nxt.startswith("/assistant"):
            nxt = url_for("assistant.bookings")
        return redirect(nxt)
    return render_template("assistant/login.html", error="Wrong password."), 401


@assistant_bp.get("/logout")
def logout():
    session.pop("assistant", None)
    return redirect(url_for("assistant.login_page"))


# ─── read-only booking list ──────────────────────────────────────────────────

_TABS = ("today", "all", "pending_payment", "confirmed", "cancelled")


@assistant_bp.get("/")
@assistant_required
def bookings():
    tab = request.args.get("tab") or "today"
    if tab not in _TABS:
        tab = "today"
    q = (request.args.get("q") or "").strip().lower()
    today = datetime.now(IST).date()

    if tab == "today":
        # Arriving, staying, or leaving today: everything active that overlaps today.
        rows = [
            b for b in database.list_bookings(limit=500)
            if b["status"] != "cancelled"
            and b["check_in"] <= today <= b["check_out"]
        ]
        rows.sort(key=lambda b: (b["check_in"], b["id"]))
    elif tab == "all":
        rows = database.list_bookings(limit=500)
    else:
        rows = database.list_bookings(status=tab, limit=500)

    if q:
        rows = [b for b in rows if q in _search_text(b)]

    return render_template(
        "assistant/bookings.html",
        bookings=rows,
        tab=tab,
        q=request.args.get("q") or "",
        today=today,
    )


def _search_text(b: dict) -> str:
    return " ".join(str(b.get(k) or "") for k in ("booking_ref", "guest_name", "phone", "email")).lower()


# ─── schedule (day-by-day rooms/meals/activities/payments) ───────────────────
# Shared by both dashboards so the owner admin and the front-desk assistant see
# exactly the same thing — same filtering rules, same figures, no drift.

SCHEDULE_MAX_DAYS = 60  # guardrail so a typo in the date range can't render a huge page


def parse_schedule_range(args, today: date) -> tuple:
    """Parse ?from=&to= query params into (start, end), clamped to SCHEDULE_MAX_DAYS.
    Returns (start, end, warning_or_None)."""
    try:
        start = date.fromisoformat(args["from"]) if args.get("from") else today
    except ValueError:
        start = today
    try:
        end = date.fromisoformat(args["to"]) if args.get("to") else start + timedelta(days=9)
    except ValueError:
        end = start + timedelta(days=9)

    if end < start:
        start, end = end, start
    warning = None
    if (end - start).days > SCHEDULE_MAX_DAYS - 1:
        end = start + timedelta(days=SCHEDULE_MAX_DAYS - 1)
        warning = f"That range was too wide — showing the first {SCHEDULE_MAX_DAYS} days."
    return start, end, warning


def build_schedule_days(start: date, end: date) -> list:
    """Day-by-day list of confirmed, paid bookings for [start, end] — room, meal plan for
    that day, activities, who's arriving/departing, and paid/pending amounts.

    Only confirmed bookings that have actually paid something — online via the WhatsApp
    QR (acknowledged advance) or in person at the desk (walk-in cash/UPI/card). A booking
    that hasn't paid anything yet hasn't really happened, so it shouldn't clutter a day's
    room/meal/activity planning.
    """
    active_bookings = [
        b for b in database.list_bookings(limit=1000)
        if b["status"] == "confirmed" and (b.get("amount_paid") or 0) > 0
    ]

    days = []
    d = start
    while d <= end:
        day_bookings = [b for b in active_bookings if b["check_in"] <= d <= b["check_out"]]
        day_bookings.sort(key=lambda b: (b["check_in"] != d, (b["room_type"] or ""), (b["guest_name"] or "")))
        days.append({
            "date": d,
            "bookings": day_bookings,
            "rooms_occupied": sum(b.get("room_count") or 1 for b in day_bookings),
            "guests": sum((b.get("adults") or 0) + (b.get("children") or 0) for b in day_bookings),
            "arrivals": sum(1 for b in day_bookings if b["check_in"] == d),
            "departures": sum(1 for b in day_bookings if b["check_out"] == d),
            "total_paid": sum(b.get("amount_paid") or 0 for b in day_bookings),
            "total_pending": sum(max((b.get("total_amount") or 0) - (b.get("amount_paid") or 0), 0) for b in day_bookings),
        })
        d += timedelta(days=1)
    return days


def schedule_presets(today: date, endpoint: str) -> list:
    """Quick-filter buttons (Today / Next 7/10/30 Days). `endpoint` is the Flask endpoint
    to link each one to — admin.schedule_view or assistant.schedule_view."""
    def _range_link(label, f, t):
        href = url_for(endpoint, **{"from": f.isoformat(), "to": t.isoformat()})
        return (label, href, f, t)

    return [
        _range_link("Today", today, today),
        _range_link("Next 7 Days", today, today + timedelta(days=6)),
        _range_link("Next 10 Days", today, today + timedelta(days=9)),
        _range_link("Next 30 Days", today, today + timedelta(days=29)),
    ]


# ─── booking detail (read-only, except recording a payment) ──────────────────

def _parse_activities(raw) -> list:
    """Activities are stored as JSON: {"Kayaking": 2, "Animal Petting": True} or a list. Returns display strings."""
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return [str(raw)]
    if isinstance(data, dict):
        out = []
        for name, value in data.items():
            if isinstance(value, bool):
                if value:
                    out.append(name)
            elif isinstance(value, (int, float)) and value > 0:
                out.append(f"{name} × {int(value)}" if value > 1 else name)
            elif value:
                out.append(f"{name} ({value})")
        return out
    if isinstance(data, list):
        return [str(x) for x in data]
    return []


@assistant_bp.get("/bookings/<int:booking_id>")
@assistant_required
def booking_detail(booking_id):
    b = database.get_booking(booking_id)
    if not b:
        abort(404)
    return render_template(
        "assistant/booking_detail.html",
        b=b,
        activities_d1=_parse_activities(b.get("activities_d1")),
        activities_d2=_parse_activities(b.get("activities_d2")),
        payments=database.list_payments(booking_id),
        today=datetime.now(IST).date(),
    )


@assistant_bp.post("/bookings/<int:booking_id>/record-payment")
@assistant_required
def booking_record_payment(booking_id):
    """Front desk records a payment handed over at the desk (cash/UPI/card) — same
    behavior as the owner admin's equivalent action, since both call record_payment()."""
    b = database.get_booking(booking_id)
    if not b:
        abort(404)
    try:
        amount = record_payment(booking_id, request.form)
    except PaymentError as e:
        flash(str(e), "err")
        return redirect(url_for("assistant.booking_detail", booking_id=booking_id))
    flash(f"₹{amount:,} payment recorded for {b['booking_ref']} and guest notified.", "ok")
    return redirect(url_for("assistant.booking_detail", booking_id=booking_id))


@assistant_bp.get("/schedule")
@assistant_required
def schedule_view():
    """Same day-by-day schedule as the owner admin sees — rooms, meals, activities,
    paid/pending — built from the exact same shared functions, so it can't drift."""
    today = datetime.now(IST).date()
    start, end, warning = parse_schedule_range(request.args, today)
    if warning:
        flash(warning, "err")
    days = build_schedule_days(start, end)
    presets = schedule_presets(today, "assistant.schedule_view")
    return render_template(
        "assistant/schedule.html",
        days=days, today=today, start=start, end=end, presets=presets,
        parse_activities=_parse_activities,
    )


# ─── walk-in booking (guest arrived without booking online) ──────────────────

@assistant_bp.route("/walk-in", methods=["GET", "POST"])
@assistant_required
def walk_in():
    if request.method == "GET":
        return render_template("assistant/walk_in.html", **walk_in_context({}))

    try:
        booking_id, _ref = book_walk_in(request.form)
    except RoomsUnavailable as e:
        flash(str(e), "err")
        return render_template("assistant/walk_in.html", **walk_in_context(request.form)), 409
    except ValueError as e:
        flash(str(e), "err")
        return render_template("assistant/walk_in.html", **walk_in_context(request.form)), 400

    return redirect(url_for("assistant.booking_detail", booking_id=booking_id))


class RoomsUnavailable(ValueError):
    """Raised when the requested room type doesn't have enough free rooms for the dates."""


class PaymentError(ValueError):
    """Raised when a payment can't be recorded (bad amount, or the booking isn't confirmed yet)."""


def walk_in_context(form) -> dict:
    """Template variables for the walk-in form. Shared by the assistant desk and the owner admin."""
    return {
        "rooms": database.list_rooms(),
        "meals": database.list_meal_plans(),
        "activities_d1": database.list_activities(day="d1"),
        "activities_d2": database.list_activities(day="d2"),
        "today": datetime.now(IST).date().isoformat(),
        "form": form,
        "advance_percent": config.ADVANCE_PERCENT,
    }


def book_walk_in(form) -> tuple:
    """Validate, price and save a walk-in booking. Returns (booking_id, booking_ref).

    Raises ValueError (bad input) or RoomsUnavailable (sold out). Used by both dashboards.
    """
    rooms = database.list_rooms()
    meals = database.list_meal_plans()
    acts_d1 = database.list_activities(day="d1")
    acts_d2 = database.list_activities(day="d2")
    today = datetime.now(IST).date()

    data = _parse_walk_in(form, rooms, meals, acts_d1, acts_d2, today)

    nights = (data["check_out"] - data["check_in"]).days
    totals = pricing.calculate_total(
        room_type=data["room_type"],
        nights=nights,
        pax=data["adults"] + data["children"],
        meal_plan_d1=data["meal_plan_d1"],
        meal_plan_sub=data["meal_plan_sub"],
        activities_d1=data["activities_d1"],
        activities_d2=data["activities_d2"],
        pickup_point=None,
        vehicle_type=None,
        room_count=data["room_count"],
    )
    total = totals["total"]
    advance = round(total * config.ADVANCE_PERCENT / 100)

    # Availability check + insert happen atomically (one DB transaction, advisory-locked on
    # the room type) so two walk-ins — or a walk-in and an online booking — racing for the
    # last room can't both succeed.
    result = database.create_booking_if_available(
        check_in=data["check_in"].isoformat(),
        check_out=data["check_out"].isoformat(),
        room_type=data["room_type"],
        room_count=data["room_count"],
        phone=data["phone"],
        guest_name=data["guest_name"],
        email=data["email"],
        adults=data["adults"],
        children=data["children"],
        nights=nights,
        special_requests=data["special_requests"],
        food_preference=None,
        veg_count=0,
        nv_count=0,
        meal_plan_d1=data["meal_plan_d1"],
        meal_plan_sub=data["meal_plan_sub"],
        arrival_mode=None,
        pickup_point=None,
        vehicle_type=None,
        activities_d1=data["activities_d1"],
        activities_d2=data["activities_d2"],
        total_amount=total,
        advance_amount=advance,
        status="confirmed",
        source="walk-in",
        acknowledged=True,
    )
    if result is None:
        raise RoomsUnavailable("Not enough rooms of that type free for these dates.")
    booking_id, booking_ref = result

    # The guest is standing right there, so record what they actually handed over — defaults
    # to the full total (the common case for a walk-in) unless a smaller amount was entered.
    amount_received = data["amount_received"] if data["amount_received"] is not None else total
    if amount_received > 0:
        database.add_payment(booking_id, amount_received, method=data["payment_method"], note="Walk-in")

    if form.get("notify_guest"):
        _send_walk_in_confirmation(
            phone=data["phone"],
            guest_name=data["guest_name"],
            booking_ref=booking_ref,
            check_in=data["check_in"].isoformat(),
            check_out=data["check_out"].isoformat(),
            nights=nights,
            room_type=data["room_type"],
            room_count=data["room_count"],
            total=total,
        )

    flash(f"Walk-in booking {booking_ref} created and confirmed.", "ok")
    return booking_id, booking_ref


def _parse_walk_in(form, rooms, meals, acts_d1, acts_d2, today) -> dict:
    """Validate the walk-in form. Raises ValueError with a message the assistant can read."""
    guest_name = (form.get("guest_name") or "").strip()
    if not guest_name:
        raise ValueError("Enter the guest's name.")

    phone = _normalize_phone(form.get("phone"))
    if not phone:
        raise ValueError("Enter a valid phone number (with or without country code).")

    check_in = _parse_date(form.get("check_in"), "Check-in")
    check_out = _parse_date(form.get("check_out"), "Check-out")
    if check_in < today:
        raise ValueError("Check-in can't be in the past.")
    if check_out <= check_in:
        raise ValueError("Check-out must be after check-in.")

    room_type = form.get("room_type") or ""
    if room_type not in {r["name"] for r in rooms}:
        raise ValueError("Pick a room type.")

    meal_names = {m["name"] for m in meals}
    meal_d1 = form.get("meal_plan_d1") or "No Meals"
    meal_sub = form.get("meal_plan_sub") or "No Meals"
    if meal_d1 not in meal_names or meal_sub not in meal_names:
        raise ValueError("Pick valid meal plans.")

    adults = _int(form.get("adults"), default=1, minimum=1)
    children = _int(form.get("children"), default=0, minimum=0)
    room_count = _int(form.get("room_count"), default=1, minimum=1)
    pax = adults + children

    activities_d1 = _parse_activity_selection(form, acts_d1, "act_d1", pax)
    activities_d2 = _parse_activity_selection(form, acts_d2, "act_d2", pax)

    amount_received_raw = (form.get("amount_received") or "").strip()
    try:
        amount_received = int(amount_received_raw) if amount_received_raw else None
    except ValueError:
        amount_received = None
    if amount_received is not None and amount_received < 0:
        raise ValueError("Amount received can't be negative.")
    payment_method = (form.get("payment_method") or "").strip() or "Cash"

    return {
        "guest_name": guest_name,
        "phone": phone,
        "email": (form.get("email") or "").strip() or None,
        "check_in": check_in,
        "check_out": check_out,
        "room_type": room_type,
        "room_count": room_count,
        "adults": adults,
        "children": children,
        "meal_plan_d1": meal_d1,
        "meal_plan_sub": meal_sub,
        "activities_d1": activities_d1,
        "activities_d2": activities_d2,
        "special_requests": (form.get("special_requests") or "").strip() or None,
        "amount_received": amount_received,
        "payment_method": payment_method,
    }


def _parse_activity_selection(form, activities: list, prefix: str, default_pax: int) -> dict:
    """Build an {activity_name: True | count} dict from walk-in checkboxes — the same shape
    the website/bot bookings store, so pricing.py and booking_detail pages work unchanged.

    Default counts match booking.html's own JS: "person"/"head" activities default to the
    whole party (everyone's presumably joining), "boat" activities default to 1 (a boat
    usually seats more than one guest, so it shouldn't default to one-per-person)."""
    selected = {}
    for a in activities:
        if not form.get(f"{prefix}_{a['key']}"):
            continue
        per = a["per_unit"]
        if per in ("person", "head"):
            selected[a["name"]] = _int(form.get(f"{prefix}_{a['key']}_count"), default=default_pax, minimum=1)
        elif per == "boat":
            selected[a["name"]] = _int(form.get(f"{prefix}_{a['key']}_count"), default=1, minimum=1)
        else:
            selected[a["name"]] = True
    return selected


def _normalize_phone(raw) -> "str | None":
    """Return digits with country code (e.g. 919876543210), matching how WhatsApp numbers are stored."""
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 10:
        digits = "91" + digits
    if 11 <= len(digits) <= 15:
        return digits
    return None


def _parse_date(value, label: str) -> date:
    try:
        return date.fromisoformat(value or "")
    except ValueError:
        raise ValueError(f"{label} date is missing or invalid.")


def _int(value, default: int, minimum: int) -> int:
    try:
        return max(int(value), minimum)
    except (TypeError, ValueError):
        return default


def _send_walk_in_confirmation(*, phone, guest_name, booking_ref, check_in, check_out,
                               nights, room_type, room_count, total):
    try:
        import whatsapp
        whatsapp.send_text(
            phone,
            f"✅ *Booking Confirmed!* 🎉\n\n"
            f"Hi {guest_name}, welcome to {database.get_setting('property_name', 'the farm')}.\n\n"
            f"Ref: *{booking_ref}*\n"
            f"Dates: {check_in} → {check_out} ({nights} night(s))\n"
            f"Room: {room_type} × {room_count}\n"
            f"Total: ₹{total:,}\n\n"
            f"Address: {database.get_setting('property_address', '')}\n"
            f"GPS: {database.get_setting('property_gps', '')}\n"
            f"Contact: {database.get_setting('property_contact', '')}",
        )
    except Exception as e:
        print(f"WA walk-in confirmation failed: {e}")


# ─── record a payment (cash / UPI / card handed over at the desk) ────────────
# Shared by both dashboards so the owner admin and the front-desk assistant
# behave identically — same validation, same WhatsApp wording, no drift.

def record_payment(booking_id: int, form) -> int:
    """Validate and record a payment against a confirmed booking. Returns the amount recorded.

    Sends the guest a WhatsApp receipt — worded differently depending on whether this
    payment fully settles the balance or leaves some still outstanding. Raises
    PaymentError with a message either dashboard can show directly to whoever's using it.
    """
    b = database.get_booking(booking_id)
    if not b:
        raise PaymentError("Booking not found.")
    if b["status"] != "confirmed":
        raise PaymentError("Only a confirmed booking can have a payment recorded against it.")

    try:
        amount = int(form.get("amount") or 0)
    except ValueError:
        amount = 0
    if amount <= 0:
        raise PaymentError("Enter a payment amount greater than ₹0.")

    method = (form.get("method") or "").strip() or None
    note = (form.get("note") or "").strip() or None

    if database.has_recent_duplicate_payment(booking_id, amount, method):
        # Almost certainly a double-click or a resubmit after a slow response, not a second
        # real payment — without this guard it would double-count the money collected.
        raise PaymentError(
            f"A payment of ₹{amount:,} was just recorded a few seconds ago for this booking — "
            "skipped so it isn't counted twice. If this really is a separate payment, wait a "
            "moment and try again."
        )

    database.add_payment(booking_id, amount, method=method, note=note)

    total = b["total_amount"] or 0
    paid_before = b["amount_paid"] or 0
    balance_remaining = max(total - (paid_before + amount), 0)
    method_label = f" ({method})" if method else ""

    try:
        import whatsapp
        if balance_remaining <= 0:
            whatsapp.send_text(
                b["phone"],
                f"✅ *Balance Payment Received!* 🎉\n\n"
                f"Ref: *{b['booking_ref']}*\n"
                f"Dates: {b['check_in']} → {b['check_out']} ({b['nights']} night(s))\n"
                f"Room: {b['room_type']} × {b.get('room_count', 1)}\n"
                f"Total: ₹{total:,}\n"
                f"Payment received{method_label}: ₹{amount:,}\n\n"
                f"Your payment is now fully settled — thank you! See you at the farm.\n\n"
                f"Address: {database.get_setting('property_address', '')}\n"
                f"GPS: {database.get_setting('property_gps', '')}\n"
                f"Contact: {database.get_setting('property_contact', '')}",
            )
        else:
            whatsapp.send_text(
                b["phone"],
                f"✅ *Payment Received* 🎉\n\n"
                f"Ref: *{b['booking_ref']}*\n"
                f"Dates: {b['check_in']} → {b['check_out']} ({b['nights']} night(s))\n"
                f"Room: {b['room_type']} × {b.get('room_count', 1)}\n"
                f"Total: ₹{total:,}\n"
                f"Payment received{method_label}: ₹{amount:,}\n"
                f"Balance remaining: ₹{balance_remaining:,}\n\n"
                f"Thank you! See you at the farm.\n\n"
                f"Address: {database.get_setting('property_address', '')}\n"
                f"GPS: {database.get_setting('property_gps', '')}\n"
                f"Contact: {database.get_setting('property_contact', '')}",
            )
    except Exception as e:
        print(f"WA payment-receipt-send failed: {e}")

    return amount
