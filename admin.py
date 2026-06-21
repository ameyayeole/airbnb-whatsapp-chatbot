"""
admin.py — Flask Blueprint for the admin dashboard.

Single-password auth (ADMIN_PASSWORD env var). Sessions kept in Flask's signed
cookie. All routes under /admin/* require login except /admin/login.
"""
import hmac
import os
import re
import time
from functools import wraps
from werkzeug.utils import secure_filename

from flask import (
    Blueprint, render_template, request, redirect, url_for, session,
    flash, abort, current_app,
)

import config
import database

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


# ─── auth ────────────────────────────────────────────────────────────────────

def _is_logged_in() -> bool:
    return bool(session.get("admin"))


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not _is_logged_in():
            return redirect(url_for("admin.login", next=request.path))
        return fn(*args, **kwargs)
    return wrapper


@admin_bp.get("/login")
def login_page():
    return render_template("admin/login.html", error=None)


@admin_bp.post("/login")
def login():
    pw = (request.form.get("password") or "").strip()
    if pw and hmac.compare_digest(pw, config.ADMIN_PASSWORD):
        session["admin"] = True
        session["logged_in_at"] = int(time.time())
        return redirect(request.args.get("next") or url_for("admin.dashboard"))
    return render_template("admin/login.html", error="Wrong password."), 401


@admin_bp.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("admin.login_page"))


# ─── dashboard ───────────────────────────────────────────────────────────────

@admin_bp.get("/")
@login_required
def dashboard():
    pending = database.list_bookings(status="pending_payment", limit=50)
    confirmed = database.list_bookings(status="confirmed", limit=10)
    all_count = len(database.list_bookings(limit=1000))
    return render_template(
        "admin/dashboard.html",
        pending=pending,
        confirmed=confirmed,
        all_count=all_count,
    )


# ─── bookings ────────────────────────────────────────────────────────────────

@admin_bp.get("/bookings")
@login_required
def bookings_list():
    status = request.args.get("status") or None
    rows = database.list_bookings(status=status, limit=500)
    return render_template("admin/bookings.html", bookings=rows, status=status)


@admin_bp.get("/bookings/<int:booking_id>")
@login_required
def booking_detail(booking_id):
    b = database.get_booking(booking_id)
    if not b:
        abort(404)
    return render_template("admin/booking_detail.html", b=b)


@admin_bp.post("/bookings/<int:booking_id>/acknowledge")
@login_required
def booking_acknowledge(booking_id):
    """Admin marks a booking as paid + confirmed. Triggers a WA message to the guest."""
    b = database.get_booking(booking_id)
    if not b:
        abort(404)
    database.update_booking_status(booking_id, "confirmed", mark_acknowledged=True)

    # Notify the guest on WhatsApp that the booking is now confirmed.
    try:
        import whatsapp
        whatsapp.send_text(
            b["phone"],
            f"✅ *Booking Confirmed!* 🎉\n\n"
            f"Ref: *{b['booking_ref']}*\n"
            f"Dates: {b['check_in']} → {b['check_out']} ({b['nights']} night(s))\n"
            f"Room: {b['room_type']} × {b.get('room_count', 1)}\n"
            f"Total: ₹{b['total_amount']:,}\n"
            f"Advance paid: ₹{b['advance_amount']:,}\n\n"
            f"We've received your payment. See you at the farm!\n\n"
            f"Address: {database.get_setting('property_address', '')}\n"
            f"GPS: {database.get_setting('property_gps', '')}\n"
            f"Contact: {database.get_setting('property_contact', '')}",
        )
    except Exception as e:
        print(f"WA confirm-send failed: {e}")

    flash(f"Booking {b['booking_ref']} confirmed and guest notified.", "ok")
    return redirect(url_for("admin.booking_detail", booking_id=booking_id))


@admin_bp.post("/bookings/<int:booking_id>/cancel")
@login_required
def booking_cancel(booking_id):
    b = database.get_booking(booking_id)
    if not b:
        abort(404)
    database.update_booking_status(booking_id, "cancelled")
    try:
        import whatsapp
        whatsapp.send_text(
            b["phone"],
            f"❌ Your booking *{b['booking_ref']}* has been cancelled.\n"
            f"Reach out if this was unexpected: {database.get_setting('property_contact', '')}",
        )
    except Exception as e:
        print(f"WA cancel-send failed: {e}")
    flash(f"Booking {b['booking_ref']} cancelled.", "ok")
    return redirect(url_for("admin.booking_detail", booking_id=booking_id))


# ─── settings: kv (property contact, owner WA, UPI, etc.) ────────────────────

_KV_FIELDS = [
    ("property_name",       "Property name", "text"),
    ("property_address",    "Address", "text"),
    ("property_gps",        "GPS link", "text"),
    ("property_contact",    "Property contact", "text"),
    ("support_email",       "Support email", "text"),
    ("check_in_time",       "Check-in time", "text"),
    ("check_out_time",      "Check-out time", "text"),
    ("advance_percent",     "Advance %", "number"),
    ("upi_vpa",             "UPI VPA (id@bank)", "text"),
    ("owner_wa_numbers",    "Owner WhatsApp numbers (comma-separated, with country code, digits only)", "text"),
    ("transport_contact",   "Transport contact", "text"),
    ("tour_guide_contact",  "Tour guide contact", "text"),
    ("sports_guide_contact","Sports guide contact", "text"),
    ("nearest_hospital",    "Nearest hospital", "text"),
    ("medical_contact",     "Medical contact", "text"),
    ("ambulance",           "Ambulance", "text"),
    ("pharmacy_info",       "Pharmacy info", "text"),
    ("cancellation_policy", "Cancellation policy", "textarea"),
]


@admin_bp.get("/settings")
@login_required
def settings_page():
    return render_template(
        "admin/settings.html",
        fields=_KV_FIELDS,
        values=database.get_all_settings(),
    )


@admin_bp.post("/settings")
@login_required
def settings_save():
    for key, _label, _typ in _KV_FIELDS:
        if key in request.form:
            database.set_setting(key, request.form.get(key, "").strip())
    flash("Settings saved.", "ok")
    return redirect(url_for("admin.settings_page"))


# ─── rooms ───────────────────────────────────────────────────────────────────

@admin_bp.get("/rooms")
@login_required
def rooms_list():
    return render_template("admin/rooms.html", rooms=database.list_rooms(active_only=False))


@admin_bp.post("/rooms")
@login_required
def rooms_save():
    room_id = request.form.get("id") or None
    database.upsert_room(
        room_id=int(room_id) if room_id else None,
        key=request.form["key"].strip(),
        name=request.form["name"].strip(),
        rate=int(request.form.get("rate") or 0),
        capacity=int(request.form.get("capacity") or 1),
        inventory=int(request.form.get("inventory") or 1),
        description=request.form.get("description", "").strip(),
        sort_order=int(request.form.get("sort_order") or 0),
        active=bool(request.form.get("active")),
    )
    flash("Room saved.", "ok")
    return redirect(url_for("admin.rooms_list"))


@admin_bp.post("/rooms/<int:room_id>/delete")
@login_required
def rooms_delete(room_id):
    database.delete_room(room_id)
    flash("Room deleted.", "ok")
    return redirect(url_for("admin.rooms_list"))


# ─── meal plans ──────────────────────────────────────────────────────────────

@admin_bp.get("/meals")
@login_required
def meals_list():
    return render_template("admin/meals.html", meals=database.list_meal_plans(active_only=False))


@admin_bp.post("/meals")
@login_required
def meals_save():
    plan_id = request.form.get("id") or None
    database.upsert_meal_plan(
        plan_id=int(plan_id) if plan_id else None,
        key=request.form["key"].strip(),
        name=request.form["name"].strip(),
        price=int(request.form.get("price") or 0),
        sort_order=int(request.form.get("sort_order") or 0),
        active=bool(request.form.get("active")),
    )
    flash("Meal plan saved.", "ok")
    return redirect(url_for("admin.meals_list"))


@admin_bp.post("/meals/<int:plan_id>/delete")
@login_required
def meals_delete(plan_id):
    database.delete_meal_plan(plan_id)
    flash("Meal plan deleted.", "ok")
    return redirect(url_for("admin.meals_list"))


# ─── activities ──────────────────────────────────────────────────────────────

@admin_bp.get("/activities")
@login_required
def activities_list():
    return render_template(
        "admin/activities.html",
        d1=database.list_activities(day="d1", active_only=False),
        d2=database.list_activities(day="d2", active_only=False),
    )


@admin_bp.post("/activities")
@login_required
def activities_save():
    activity_id = request.form.get("id") or None
    database.upsert_activity(
        activity_id=int(activity_id) if activity_id else None,
        day=request.form["day"].strip(),
        key=request.form["key"].strip(),
        name=request.form["name"].strip(),
        price=int(request.form.get("price") or 0),
        per_unit=request.form.get("per_unit", "group"),
        duration=request.form.get("duration", "").strip(),
        note=request.form.get("note", "").strip(),
        is_free=bool(request.form.get("is_free")),
        sort_order=int(request.form.get("sort_order") or 0),
        active=bool(request.form.get("active")),
    )
    flash("Activity saved.", "ok")
    return redirect(url_for("admin.activities_list"))


@admin_bp.post("/activities/<int:activity_id>/delete")
@login_required
def activities_delete(activity_id):
    database.delete_activity(activity_id)
    flash("Activity deleted.", "ok")
    return redirect(url_for("admin.activities_list"))


# ─── transport (pickup points + vehicles) ────────────────────────────────────

@admin_bp.get("/transport")
@login_required
def transport_list():
    return render_template(
        "admin/transport.html",
        pickup_points=database.list_pickup_points(active_only=False),
        vehicles=database.list_vehicle_types(active_only=False),
    )


@admin_bp.post("/transport/pickup")
@login_required
def transport_save_pickup():
    point_id = request.form.get("id") or None
    database.upsert_pickup_point(
        point_id=int(point_id) if point_id else None,
        name=request.form["name"].strip(),
        base_fare=int(request.form.get("base_fare") or 0),
        sort_order=int(request.form.get("sort_order") or 0),
        active=bool(request.form.get("active")),
    )
    flash("Pickup point saved.", "ok")
    return redirect(url_for("admin.transport_list"))


@admin_bp.post("/transport/pickup/<int:point_id>/delete")
@login_required
def transport_delete_pickup(point_id):
    database.delete_pickup_point(point_id)
    flash("Pickup point deleted.", "ok")
    return redirect(url_for("admin.transport_list"))


@admin_bp.post("/transport/vehicle")
@login_required
def transport_save_vehicle():
    vehicle_id = request.form.get("id") or None
    database.upsert_vehicle(
        vehicle_id=int(vehicle_id) if vehicle_id else None,
        key=request.form["key"].strip(),
        name=request.form["name"].strip(),
        multiplier=float(request.form.get("multiplier") or 1.0),
        description=request.form.get("description", "").strip(),
        sort_order=int(request.form.get("sort_order") or 0),
        active=bool(request.form.get("active")),
    )
    flash("Vehicle saved.", "ok")
    return redirect(url_for("admin.transport_list"))


@admin_bp.post("/transport/vehicle/<int:vehicle_id>/delete")
@login_required
def transport_delete_vehicle(vehicle_id):
    database.delete_vehicle(vehicle_id)
    flash("Vehicle deleted.", "ok")
    return redirect(url_for("admin.transport_list"))


# ─── photos & QR uploads ─────────────────────────────────────────────────────

_ALLOWED_EXT = {"png", "jpg", "jpeg", "gif", "webp"}


def _allowed(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in _ALLOWED_EXT


def _save_upload(file_storage, prefix: str = "") -> str:
    os.makedirs(config.UPLOAD_FOLDER, exist_ok=True)
    base = secure_filename(file_storage.filename or "upload.png")
    if not _allowed(base):
        raise ValueError("File type not allowed. Use PNG/JPG/JPEG/GIF/WEBP.")
    ts = int(time.time())
    fname = re.sub(r"[^a-zA-Z0-9._-]", "_", f"{prefix}{ts}_{base}")
    path = os.path.join(config.UPLOAD_FOLDER, fname)
    file_storage.save(path)
    return fname


@admin_bp.get("/photos")
@login_required
def photos_page():
    # Slots: hero, room-<key>, gallery, payment_qr
    photos = database.list_photos()
    by_slot = {}
    for p in photos:
        by_slot.setdefault(p["slot"], []).append(p)
    rooms = database.list_rooms(active_only=False)
    qr_filename = database.get_setting("payment_qr_filename", "")
    return render_template(
        "admin/photos.html",
        by_slot=by_slot,
        rooms=rooms,
        qr_filename=qr_filename,
    )


@admin_bp.post("/photos/upload")
@login_required
def photos_upload():
    slot = (request.form.get("slot") or "").strip()
    alt = (request.form.get("alt_text") or "").strip()
    if not slot:
        flash("Pick a slot.", "err")
        return redirect(url_for("admin.photos_page"))
    file = request.files.get("file")
    if not file or not file.filename:
        flash("No file selected.", "err")
        return redirect(url_for("admin.photos_page"))
    try:
        fname = _save_upload(file, prefix="ph_")
    except ValueError as e:
        flash(str(e), "err")
        return redirect(url_for("admin.photos_page"))
    database.add_photo(slot=slot, filename=fname, alt_text=alt)
    flash("Photo uploaded.", "ok")
    return redirect(url_for("admin.photos_page"))


@admin_bp.post("/photos/<int:photo_id>/delete")
@login_required
def photos_delete(photo_id):
    fname = database.delete_photo(photo_id)
    if fname:
        try:
            os.remove(os.path.join(config.UPLOAD_FOLDER, fname))
        except OSError:
            pass
    flash("Photo deleted.", "ok")
    return redirect(url_for("admin.photos_page"))


# ─── feedback management ─────────────────────────────────────────────────────

@admin_bp.get("/feedback")
@login_required
def feedback_list():
    status = request.args.get("status") or None
    items = database.list_feedback(status=status, limit=200)
    return render_template("admin/feedback.html", items=items, status=status)


@admin_bp.post("/feedback/<int:feedback_id>/approve")
@login_required
def feedback_approve(feedback_id):
    database.update_feedback_status(feedback_id, "approved")
    flash("Feedback approved — visible on the public site.", "ok")
    return redirect(url_for("admin.feedback_list"))


@admin_bp.post("/feedback/<int:feedback_id>/reject")
@login_required
def feedback_reject(feedback_id):
    database.update_feedback_status(feedback_id, "rejected")
    flash("Feedback rejected.", "ok")
    return redirect(url_for("admin.feedback_list"))


@admin_bp.post("/feedback/media/<int:media_id>/toggle")
@login_required
def feedback_media_toggle(media_id):
    now = database.toggle_feedback_media_approval(media_id)
    flash("Photo " + ("approved for showcase." if now else "unapproved."), "ok")
    return redirect(url_for("admin.feedback_list"))


@admin_bp.post("/feedback/media/<int:media_id>/delete")
@login_required
def feedback_media_delete(media_id):
    fname = database.delete_feedback_media(media_id)
    if fname:
        try:
            os.remove(os.path.join(config.UPLOAD_FOLDER, fname))
        except OSError:
            pass
    flash("Media deleted.", "ok")
    return redirect(url_for("admin.feedback_list"))


@admin_bp.post("/bookings/<int:booking_id>/send-feedback")
@login_required
def booking_send_feedback(booking_id):
    """Manually trigger the feedback link on WhatsApp from the booking page."""
    b = database.get_booking(booking_id)
    if not b:
        abort(404)
    from app import send_feedback_request  # imported lazily to avoid circular import at module load
    url = send_feedback_request(b)
    flash(f"Feedback link sent to {b['guest_name']} on WhatsApp.", "ok")
    return redirect(url_for("admin.booking_detail", booking_id=booking_id))


@admin_bp.post("/payment-qr/upload")
@login_required
def payment_qr_upload():
    file = request.files.get("file")
    if not file or not file.filename:
        flash("No file selected.", "err")
        return redirect(url_for("admin.photos_page"))
    try:
        fname = _save_upload(file, prefix="qr_")
    except ValueError as e:
        flash(str(e), "err")
        return redirect(url_for("admin.photos_page"))
    database.set_setting("payment_qr_filename", fname)
    flash("Payment QR updated.", "ok")
    return redirect(url_for("admin.photos_page"))


