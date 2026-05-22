from flask import Flask, request, jsonify
import database
import bot
import config

app = Flask(__name__)
database.init_db()


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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=config.PORT, debug=False)
