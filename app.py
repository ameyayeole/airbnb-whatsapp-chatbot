from flask import Flask, request, jsonify, render_template
import database
import bot
import config

app = Flask(__name__)
database.init_db()


@app.get("/webhook")
def verify():
    mode      = request.args.get("hub.mode")
    token     = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == config.VERIFY_TOKEN:
        return challenge, 200
    return "Forbidden", 403


@app.post("/webhook")
def webhook():
    payload = request.get_json(silent=True) or {}
    parsed  = __import__("whatsapp").parse_incoming(payload)
    if parsed:
        bot.handle_message(parsed["phone"], parsed["msg_type"], parsed["content"])
    return jsonify({"status": "ok"}), 200


@app.get("/select-dates")
def select_dates_page():
    phone = request.args.get("phone", "")
    return render_template("select_dates.html", phone=phone)


@app.post("/dates-selected")
def dates_selected():
    data      = request.get_json(silent=True) or {}
    phone     = data.get("phone")
    check_in  = data.get("check_in")
    check_out = data.get("check_out")

    if not all([phone, check_in, check_out]):
        return jsonify({"error": "Missing data"}), 400

    bot.inject_dates(phone, check_in, check_out)
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=config.PORT, debug=False)
