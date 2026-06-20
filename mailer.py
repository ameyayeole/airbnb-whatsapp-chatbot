"""
mailer.py — booking confirmation emails (plain SMTP, no extra deps).
"""
import smtplib
import ssl
from email.message import EmailMessage

import config


def _smtp_configured() -> bool:
    return bool(config.SMTP_HOST and config.SMTP_USER and config.SMTP_PASSWORD)


def send_email(to: str, subject: str, body: str) -> bool:
    """Returns True on success, False on failure (failures are logged, not raised)."""
    if not _smtp_configured():
        print("MAILER skipped — SMTP not configured (set SMTP_HOST/USER/PASSWORD in .env).")
        return False
    if not to:
        print("MAILER skipped — no recipient.")
        return False

    msg = EmailMessage()
    msg["From"] = config.SMTP_FROM
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=15) as s:
            s.starttls(context=ctx)
            s.login(config.SMTP_USER, config.SMTP_PASSWORD)
            s.send_message(msg)
        print(f"MAILER → sent to {to}: {subject}")
        return True
    except Exception as e:
        print(f"MAILER failed for {to}: {e}")
        return False


def send_booking_confirmation_guest(
    *, guest_name: str, email: str, booking_ref: str,
    check_in: str, check_out: str, nights: int,
    room_type: str, room_count: int,
    total_amount: int, advance_amount: int,
) -> bool:
    body = (
        f"Hi {guest_name},\n\n"
        f"Thank you for your booking request at {config.PROPERTY_NAME}!\n\n"
        f"  Booking ref : {booking_ref}\n"
        f"  Check-in    : {check_in}  ({config.CHECK_IN_TIME})\n"
        f"  Check-out   : {check_out}  ({config.CHECK_OUT_TIME})\n"
        f"  Nights      : {nights}\n"
        f"  Room        : {room_type} x {room_count}\n"
        f"  Estimated total : Rs. {total_amount:,}\n"
        f"  Advance ({config.ADVANCE_PERCENT}%)  : Rs. {advance_amount:,}\n\n"
        f"We will confirm availability and share payment details shortly.\n\n"
        f"Address : {config.PROPERTY_ADDRESS}\n"
        f"Contact : {config.PROPERTY_CONTACT}\n\n"
        f"— {config.BOT_NAME}, {config.PROPERTY_NAME}\n"
    )
    return send_email(
        to=email,
        subject=f"Booking received — {booking_ref} — {config.PROPERTY_NAME}",
        body=body,
    )


def send_booking_notification_owner(
    *, guest_name: str, email: str, phone: str, booking_ref: str,
    check_in: str, check_out: str, nights: int,
    adults: int, children: int,
    room_type: str, room_count: int,
    food_preference, meal_plan_d1: str, meal_plan_sub: str,
    arrival_mode, pickup_point, vehicle_type,
    activities_d1: dict, activities_d2: dict,
    special_requests, total_amount: int, advance_amount: int,
) -> bool:
    def _fmt_acts(d: dict) -> str:
        return ", ".join(f"{k} ({v})" for k, v in d.items()) if d else "—"

    body = (
        f"NEW BOOKING REQUEST — {booking_ref}\n"
        f"{'-' * 50}\n\n"
        f"Guest         : {guest_name}\n"
        f"Email         : {email}\n"
        f"Phone (WA)    : +{phone}\n\n"
        f"Check-in      : {check_in}\n"
        f"Check-out     : {check_out}\n"
        f"Nights        : {nights}\n"
        f"Adults        : {adults}\n"
        f"Children      : {children}\n\n"
        f"Room          : {room_type} x {room_count}\n\n"
        f"Food pref     : {food_preference or 'No meals'}\n"
        f"Meal plan D1  : {meal_plan_d1}\n"
        f"Meal plan D2+ : {meal_plan_sub}\n\n"
        f"Arrival       : {arrival_mode or '—'}\n"
        f"Pickup point  : {pickup_point or '—'}\n"
        f"Vehicle       : {vehicle_type or '—'}\n\n"
        f"Day 1 acts    : {_fmt_acts(activities_d1)}\n"
        f"Day 2 acts    : {_fmt_acts(activities_d2)}\n\n"
        f"Special reqs  : {special_requests or '—'}\n\n"
        f"Estimated total : Rs. {total_amount:,}\n"
        f"Advance ({config.ADVANCE_PERCENT}%)  : Rs. {advance_amount:,}\n"
    )
    return send_email(
        to=config.SUPPORT_EMAIL,
        subject=f"[{config.PROPERTY_NAME}] New booking — {booking_ref} — {guest_name}",
        body=body,
    )
