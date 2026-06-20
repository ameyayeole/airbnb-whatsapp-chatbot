from flask import Flask, request, jsonify, render_template, abort
import database
import bot
import config
import pricing

app = Flask(__name__)
database.init_db()


@app.get("/")
def home():
    wa_link = f"https://wa.me/{config.WA_BUSINESS_NUMBER}?text=Hi"
    return render_template("home.html", wa_link=wa_link)


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

        # Notify guest on WhatsApp that we received the booking.
        try:
            __import__("whatsapp").send_text(
                rec["phone"],
                f"✅ Booking received!\n\n"
                f"Ref: *{booking_ref}*\n"
                f"Dates: {data['check_in']} → {data['check_out']} ({data['nights']} night(s))\n"
                f"Room: {data['room_type']} × {data.get('room_count', 1)}\n"
                f"Estimated total: ₹{total_amount:,}\n"
                f"Advance ({config.ADVANCE_PERCENT}%): ₹{advance_amount:,}\n\n"
                f"We'll confirm availability and share payment details shortly. — {config.BOT_NAME}"
            )
        except Exception as e:
            print(f"WA notify failed: {e}")

        return jsonify({"ok": True, "booking_id": booking_id, "booking_ref": booking_ref, "total": total_amount}), 200
    except Exception as e:
        print(f"Booking save failed: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=config.PORT, debug=False)
