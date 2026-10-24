"""
assistant.py — read-only front-desk dashboard for the hotel assistant.

Separate password (ASSISTANT_PASSWORD) and its own session flag, so signing in
here never grants access to the owner admin. Everything here only reads bookings,
except the walk-in form, which creates a confirmed booking for a guest who
arrived at the farm without booking online.
"""
import hmac
import json
import re
from datetime import date, datetime
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


# ─── read-only booking detail ────────────────────────────────────────────────

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
        today=datetime.now(IST).date(),
    )


# ─── walk-in booking (guest arrived without booking online) ──────────────────

@assistant_bp.route("/walk-in", methods=["GET", "POST"])
@assistant_required
def walk_in():
    rooms = database.list_rooms()
    meals = database.list_meal_plans()
    today = datetime.now(IST).date()

    if request.method == "GET":
        return _render_walk_in(rooms, meals, today, form={})

    form = request.form
    try:
        data = _parse_walk_in(form, rooms, meals, today)
    except ValueError as e:
        flash(str(e), "err")
        return _render_walk_in(rooms, meals, today, form=form), 400

    if not database.check_availability(
        data["check_in"].isoformat(), data["check_out"].isoformat(),
        data["room_type"], data["room_count"],
    ):
        flash("Not enough rooms of that type free for these dates.", "err")
        return _render_walk_in(rooms, meals, today, form=form), 409

    nights = (data["check_out"] - data["check_in"]).days
    totals = pricing.calculate_total(
        room_type=data["room_type"],
        nights=nights,
        pax=data["adults"] + data["children"],
        meal_plan_d1=data["meal_plan_d1"],
        meal_plan_sub=data["meal_plan_sub"],
        activities_d1={},
        activities_d2={},
        pickup_point=None,
        vehicle_type=None,
        room_count=data["room_count"],
    )
    total = totals["total"]
    advance = round(total * config.ADVANCE_PERCENT / 100)

    booking_id, booking_ref = database.create_booking(
        phone=data["phone"],
        guest_name=data["guest_name"],
        email=data["email"],
        adults=data["adults"],
        children=data["children"],
        check_in=data["check_in"].isoformat(),
        check_out=data["check_out"].isoformat(),
        nights=nights,
        special_requests=data["special_requests"],
        room_type=data["room_type"],
        room_count=data["room_count"],
        food_preference=None,
        veg_count=0,
        nv_count=0,
        meal_plan_d1=data["meal_plan_d1"],
        meal_plan_sub=data["meal_plan_sub"],
        arrival_mode=None,
        pickup_point=None,
        vehicle_type=None,
        activities_d1={},
        activities_d2={},
        total_amount=total,
        advance_amount=advance,
        status="confirmed",
        source="walk-in",
        acknowledged=True,
    )

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
    return redirect(url_for("assistant.booking_detail", booking_id=booking_id))


def _render_walk_in(rooms, meals, today, form):
    return render_template(
        "assistant/walk_in.html",
        rooms=rooms,
        meals=meals,
        today=today.isoformat(),
        form=form,
        advance_percent=config.ADVANCE_PERCENT,
    )


def _parse_walk_in(form, rooms, meals, today) -> dict:
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
        "special_requests": (form.get("special_requests") or "").strip() or None,
    }


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
