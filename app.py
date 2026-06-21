import json
import os

from flask import Flask, request, jsonify, render_template, abort, send_from_directory
import database
import bot
import config
import pricing
from admin import admin_bp

app = Flask(__name__)
app.secret_key = config.SECRET_KEY
app.register_blueprint(admin_bp)
database.init_db()
os.makedirs(config.UPLOAD_FOLDER, exist_ok=True)


@app.get("/uploads/<path:filename>")
def uploads(filename):
    """Serves admin-uploaded images (photos + payment QR) to the public site."""
    return send_from_directory(config.UPLOAD_FOLDER, filename)


@app.get("/")
def home():
    wa_link = f"https://wa.me/{config.WA_BUSINESS_NUMBER}?text=Hi"
    rooms = database.list_rooms()
    photos = database.list_photos()
    hero_photo = next((p for p in photos if p["slot"] == "hero"), None)
    room_photos = {p["slot"].split("room-", 1)[1]: p for p in photos if p["slot"].startswith("room-")}
    gallery_photos = [p for p in photos if p["slot"] == "gallery"]
    return render_template(
        "home.html",
        wa_link=wa_link,
        s=database.get_all_settings(),
        rooms=rooms,
        meal_plans=database.list_meal_plans(),
        activities_d1=database.list_activities(day="d1"),
        activities_d2=database.list_activities(day="d2"),
        pickup_points=database.list_pickup_points(),
        hero_photo=hero_photo,
        room_photos=room_photos,
        gallery_photos=gallery_photos,
        reviews=database.list_approved_feedback(limit=6),
        guest_media=database.list_approved_feedback_media(limit=12),
    )


@app.get("/webhook")
def verify():
    mode  = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    print(f"WEBHOOK VERIFY → mode={mode} token={token} challenge={challenge}")

    if mode == "subscribe" and token == config.VERIFY_TOKEN:
        print("VERIFY SUCCESS")
        return challenge, 200
    print(f"VERIFY FAILED — expected token: {config.VERIFY_TOKEN}")
    return "Forbidden", 403


@app.post("/webhook")
def webhook():
    payload = request.get_json(silent=True) or {}
    parsed = __import__("whatsapp").parse_incoming(payload)

    if parsed:
        bot.handle_message(parsed["phone"], parsed["msg_type"], parsed["content"])

    return jsonify({"status": "ok"}), 200


def _booking_page_data() -> dict:
    """Returns JSON-serializable dicts used by booking.html's JS."""
    rooms = database.list_rooms()
    meals = database.list_meal_plans()
    a_d1 = database.list_activities(day="d1")
    a_d2 = database.list_activities(day="d2")
    pickup = database.list_pickup_points()
    vehicles = database.list_vehicle_types()

    rooms_js = {r["name"]: {"cap": r["capacity"], "rate": r["rate"], "avail": r["inventory"]} for r in rooms}
    meals_js = {m["name"]: m["price"] for m in meals}
    pickup_js = {p["name"]: p["base_fare"] for p in pickup}
    vehicles_js = {v["name"]: v["multiplier"] for v in vehicles}

    def _act_js(items):
        return [{"id": a["name"], "price": a["price"], "per": a["per_unit"]} for a in items]

    def _note(a):
        if a["is_free"]:
            return f"Free{' · ' + a['duration'] if a['duration'] else ''}"
        unit = "guest" if a["per_unit"] == "person" else a["per_unit"]
        bits = [f"₹{a['price']} / {unit}"]
        if a["duration"]: bits.append(a["duration"])
        if a["note"]: bits.append(a["note"])
        return " · ".join(bits)

    notes_js = {a["name"]: _note(a) for a in a_d1 + a_d2}

    return {
        "rooms_json": json.dumps(rooms_js),
        "meals_json": json.dumps(meals_js),
        "pickup_json": json.dumps(pickup_js),
        "vehicles_json": json.dumps(vehicles_js),
        "activities_d1_json": json.dumps(_act_js(a_d1)),
        "activities_d2_json": json.dumps(_act_js(a_d2)),
        "notes_json": json.dumps(notes_js),
    }


@app.get("/book/<token>")
def book_page(token):
    rec = database.get_booking_token(token)
    if not rec:
        abort(404)
    return render_template(
        "booking.html",
        token=token,
        guest_name=rec["guest_name"],
        email=rec["email"],
        phone=rec["phone"],
        **_booking_page_data(),
    )


@app.post("/api/book")
def api_book():
    data = request.get_json(silent=True) or {}
    token = data.get("token")
    rec = database.get_booking_token(token) if token else None
    if not rec:
        return jsonify({"ok": False, "error": "Invalid or expired booking link."}), 400

    try:
        if not database.check_availability(
            data["check_in"], data["check_out"], data["room_type"], int(data.get("room_count", 1))
        ):
            return jsonify({"ok": False, "error": "Selected room is no longer available for these dates."}), 409
    except Exception as e:
        return jsonify({"ok": False, "error": f"Availability check failed: {e}"}), 500

    try:
        # Recompute server-side so the client can't tamper with totals.
        activities_d1 = data.get("activities_d1") or {}
        activities_d2 = data.get("activities_d2") or {}
        pax = int(data.get("adults", 0)) + int(data.get("children", 0))
        totals = pricing.calculate_total(
            room_type=data["room_type"],
            nights=int(data["nights"]),
            pax=pax,
            meal_plan_d1=data.get("meal_plan_d1", "No Meals"),
            meal_plan_sub=data.get("meal_plan_sub", "No Meals"),
            activities_d1=activities_d1,
            activities_d2=activities_d2,
            pickup_point=data.get("pickup_point"),
            vehicle_type=data.get("vehicle_type"),
            room_count=int(data.get("room_count", 1)),
        )
        total_amount = totals["total"]
        advance_amount = round(total_amount * config.ADVANCE_PERCENT / 100)

        booking_id, booking_ref = database.create_booking(
            phone=rec["phone"],
            guest_name=rec["guest_name"],
            email=rec["email"],
            adults=int(data.get("adults", 0)),
            children=int(data.get("children", 0)),
            check_in=data["check_in"],
            check_out=data["check_out"],
            nights=int(data["nights"]),
            special_requests=data.get("special_requests"),
            room_type=data["room_type"],
            room_count=int(data.get("room_count", 1)),
            food_preference=data.get("food_preference"),
            veg_count=int(data.get("veg_count", 0)),
            nv_count=int(data.get("nv_count", 0)),
            meal_plan_d1=data.get("meal_plan_d1", "No Meals"),
            meal_plan_sub=data.get("meal_plan_sub", "No Meals"),
            arrival_mode=data.get("arrival_mode"),
            pickup_point=data.get("pickup_point"),
            vehicle_type=data.get("vehicle_type"),
            activities_d1=activities_d1,
            activities_d2=activities_d2,
            total_amount=total_amount,
            advance_amount=advance_amount,
        )

        database.mark_token_used(token)

        # ── Send payment QR + instructions to the GUEST ──────────────────────
        try:
            _send_payment_message(
                phone=rec["phone"],
                guest_name=rec["guest_name"],
                booking_ref=booking_ref,
                check_in=data["check_in"],
                check_out=data["check_out"],
                nights=int(data["nights"]),
                room_type=data["room_type"],
                room_count=int(data.get("room_count", 1)),
                total_amount=total_amount,
                advance_amount=advance_amount,
            )
        except Exception as e:
            print(f"WA guest payment-message failed: {e}")

        # ── Notify all OWNERS on WhatsApp ───────────────────────────────────
        try:
            _notify_owners(
                booking_ref=booking_ref,
                guest_name=rec["guest_name"],
                phone=rec["phone"],
                email=rec["email"],
                check_in=data["check_in"],
                check_out=data["check_out"],
                nights=int(data["nights"]),
                adults=int(data.get("adults", 0)),
                children=int(data.get("children", 0)),
                room_type=data["room_type"],
                room_count=int(data.get("room_count", 1)),
                total_amount=total_amount,
                advance_amount=advance_amount,
                special_requests=data.get("special_requests"),
            )
        except Exception as e:
            print(f"WA owner-notify failed: {e}")

        return jsonify({"ok": True, "booking_id": booking_id, "booking_ref": booking_ref, "total": total_amount, "advance": advance_amount}), 200
    except Exception as e:
        print(f"Booking save failed: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


def _send_payment_message(*, phone, guest_name, booking_ref, check_in, check_out, nights,
                          room_type, room_count, total_amount, advance_amount):
    """Send the guest a QR (if uploaded) + payment instructions on WhatsApp."""
    import whatsapp
    qr_filename = database.get_setting("payment_qr_filename", "")
    upi_vpa = database.get_setting("upi_vpa", "")
    advance_pct = int(database.get_setting("advance_percent", "50") or 50)

    caption = (
        f"💳 *Proceed to payment*\n\n"
        f"Ref: *{booking_ref}*\n"
        f"Hi {guest_name}, here are your booking details:\n\n"
        f"• Dates: {check_in} → {check_out} ({nights} night(s))\n"
        f"• Room: {room_type} × {room_count}\n"
        f"• Total: ₹{total_amount:,}\n"
        f"• Advance ({advance_pct}%): *₹{advance_amount:,}*\n\n"
        + (f"UPI: `{upi_vpa}`\n" if upi_vpa else "")
        + "Scan the QR above to pay the advance.\n\n"
        "🕐 *Once the farm owner confirms your payment, "
        "you'll receive your full booking confirmation here.*"
    )

    if qr_filename:
        image_url = f"{config.BASE_URL.rstrip('/')}/uploads/{qr_filename}"
        whatsapp.send_image(phone, image_url, caption=caption)
    else:
        # No QR uploaded yet — send text-only
        whatsapp.send_text(
            phone,
            caption + "\n\n_(Payment QR not yet configured — please contact the farm.)_",
        )


def _notify_owners(*, booking_ref, guest_name, phone, email, check_in, check_out, nights,
                   adults, children, room_type, room_count, total_amount, advance_amount,
                   special_requests):
    """Send a 'new booking' alert to every owner WhatsApp number in settings."""
    import whatsapp
    numbers_raw = database.get_setting("owner_wa_numbers", "")
    numbers = [n.strip() for n in numbers_raw.replace(";", ",").split(",") if n.strip()]
    if not numbers:
        return

    admin_url = f"{config.BASE_URL.rstrip('/')}/admin/bookings"
    msg = (
        f"🛎️ *New booking — {booking_ref}*\n\n"
        f"Guest: {guest_name}\n"
        f"Phone: +{phone}\n"
        f"Email: {email}\n\n"
        f"Dates: {check_in} → {check_out} ({nights} night(s))\n"
        f"Guests: {adults} adult(s){f' + {children} child(ren)' if children else ''}\n"
        f"Room: {room_type} × {room_count}\n\n"
        f"Total: ₹{total_amount:,}\n"
        f"Advance due: *₹{advance_amount:,}*\n"
        + (f"\nSpecial requests: {special_requests}\n" if special_requests else "")
        + f"\n✅ When the guest pays, acknowledge here:\n{admin_url}"
    )

    for num in numbers:
        try:
            whatsapp.send_text(num, msg)
        except Exception as e:
            print(f"Owner notify failed for {num}: {e}")


def send_feedback_request(booking: dict) -> str:
    """Generate a feedback token and WhatsApp the link to the guest. Returns the URL."""
    import secrets
    import whatsapp
    token = secrets.token_urlsafe(16)
    database.create_feedback_token(token=token, booking_id=booking["id"])
    database.mark_booking_feedback_sent(booking["id"])
    url = f"{config.BASE_URL.rstrip('/')}/feedback/{token}"
    try:
        whatsapp.send_text(
            booking["phone"],
            f"Hi {booking['guest_name']} 🌾\n\n"
            f"Hope you had a wonderful stay at {database.get_setting('property_name', 'our farm')}!\n\n"
            f"We'd love your feedback (it takes a minute):\n"
            f"{url}\n\n"
            f"Drop a few photos too if you'd like — we'd love to feature them on our website!"
        )
    except Exception as e:
        print(f"WA feedback-link send failed: {e}")
    return url


@app.get("/feedback/<token>")
def feedback_form(token):
    rec = database.get_feedback_token(token)
    if not rec:
        abort(404)
    b = database.get_booking(rec["booking_id"]) or {}
    return render_template(
        "feedback.html",
        token=token,
        guest_name=b.get("guest_name", "there"),
        booking_ref=b.get("booking_ref", ""),
        already_used=rec["used"],
    )


@app.post("/api/feedback")
def api_feedback():
    data = request.get_json(silent=True) or {}
    token = data.get("token")
    rec = database.get_feedback_token(token) if token else None
    if not rec:
        return jsonify({"ok": False, "error": "Invalid feedback link."}), 400
    if rec["used"]:
        return jsonify({"ok": False, "error": "This feedback link has already been used."}), 409

    try:
        rating = int(data.get("rating") or 0)
        if rating < 1 or rating > 5:
            return jsonify({"ok": False, "error": "Rating must be 1–5."}), 400
        booking = database.get_booking(rec["booking_id"]) or {}
        fid = database.create_feedback(
            booking_id=rec["booking_id"],
            booking_ref=booking.get("booking_ref", ""),
            guest_name=booking.get("guest_name", ""),
            rating=rating,
            comment=(data.get("comment") or "").strip(),
        )
        database.mark_feedback_token_used(token)
        return jsonify({"ok": True, "feedback_id": fid}), 200
    except Exception as e:
        print(f"Feedback save failed: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


@app.post("/api/feedback/<int:feedback_id>/media")
def api_feedback_media(feedback_id):
    """Multipart upload, accepts images/videos."""
    from werkzeug.utils import secure_filename
    import re as _re
    import time as _time

    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify({"ok": False, "error": "No file."}), 400

    fname_raw = secure_filename(file.filename or "upload")
    ext = fname_raw.rsplit(".", 1)[-1].lower() if "." in fname_raw else ""
    if ext in {"png", "jpg", "jpeg", "gif", "webp"}:
        kind = "image"
    elif ext in {"mp4", "mov", "webm", "m4v"}:
        kind = "video"
    else:
        return jsonify({"ok": False, "error": "Unsupported file type."}), 400

    os.makedirs(config.UPLOAD_FOLDER, exist_ok=True)
    fname = _re.sub(r"[^a-zA-Z0-9._-]", "_", f"fb_{feedback_id}_{int(_time.time())}_{fname_raw}")
    file.save(os.path.join(config.UPLOAD_FOLDER, fname))
    mid = database.add_feedback_media(feedback_id=feedback_id, filename=fname, kind=kind)
    return jsonify({"ok": True, "id": mid, "url": f"/uploads/{fname}", "kind": kind}), 200


# ── auto-feedback cron sweep (hit by an external cron-job daily) ────────────

@app.get("/cron/feedback-sweep")
def cron_feedback_sweep():
    """Hit me once a day (e.g. cron-job.org) with ?key=<SECRET_KEY>."""
    if request.args.get("key") != config.SECRET_KEY:
        abort(403)
    due = database.list_bookings_due_for_feedback(days_after_checkout=1)
    sent = []
    for b in due:
        try:
            send_feedback_request(b)
            sent.append(b["booking_ref"])
        except Exception as e:
            print(f"Sweep send failed for {b.get('booking_ref')}: {e}")
    return jsonify({"ok": True, "sent": sent, "count": len(sent)})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=config.PORT, debug=False)
