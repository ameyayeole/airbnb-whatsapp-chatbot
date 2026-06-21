import requests
import config

_BASE = f"https://graph.facebook.com/v18.0/{config.PHONE_NUMBER_ID}/messages"
_HEADERS = {
    "Authorization": f"Bearer {config.WHATSAPP_TOKEN}",
    "Content-Type": "application/json",
}


def _post(payload: dict):
    requests.post(_BASE, json=payload, headers=_HEADERS, timeout=10)


def send_text(phone: str, message: str):
    _post({
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "text",
        "text": {"body": message},
    })


def send_image(phone: str, image_url: str, caption: str = ""):
    """Send an image via a public URL (e.g. the admin-uploaded payment QR)."""
    _post({
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "image",
        "image": {"link": image_url, "caption": caption},
    })


def send_buttons(phone: str, body: str, buttons: list[dict]):
    """
    buttons: [{"id": "btn_id", "title": "Button Label"}, ...]
    Max 3 buttons.
    """
    _post({
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": b["id"], "title": b["title"]}}
                    for b in buttons[:3]
                ]
            },
        },
    })


def send_list(phone: str, body: str, button_label: str, sections: list[dict]):
    """
    sections: [{"title": "Section", "rows": [{"id": "row_id", "title": "Row title", "description": "..."}]}]
    """
    _post({
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {"text": body},
            "action": {
                "button": button_label,
                "sections": sections,
            },
        },
    })


def parse_incoming(payload: dict) -> dict | None:
    """
    Returns {"phone": str, "msg_type": str, "content": str} or None if not a user message.
    msg_type: "text" | "button_reply" | "list_reply"
    content: the text, button id, or list row id
    """
    try:
        entry = payload["entry"][0]
        change = entry["changes"][0]["value"]
        msg = change["messages"][0]
    except (KeyError, IndexError):
        return None

    phone = msg["from"]
    mtype = msg["type"]

    if mtype == "text":
        return {"phone": phone, "msg_type": "text", "content": msg["text"]["body"].strip()}

    if mtype == "interactive":
        itype = msg["interactive"]["type"]
        if itype == "button_reply":
            return {
                "phone": phone,
                "msg_type": "button_reply",
                "content": msg["interactive"]["button_reply"]["id"],
            }
        if itype == "list_reply":
            return {
                "phone": phone,
                "msg_type": "list_reply",
                "content": msg["interactive"]["list_reply"]["id"],
            }

    return None
