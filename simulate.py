#!/usr/bin/env python3
"""
simulate.py — Terminal simulator for Mondys Organic Farm WhatsApp bot.

Patches the `whatsapp` module so every send_* call prints to stdout
instead of hitting the real WhatsApp API. Then reads your input and
feeds it through the same handle_message() that the live bot uses.

Usage:
    source venv/bin/activate
    python simulate.py
    python simulate.py --phone 911234567890   # custom test phone
"""

import argparse
import sys
import types

# ── Patch whatsapp BEFORE importing bot ───────────────────────────────────────

_BOLD_RE  = None  # lazy import

def _strip_wa(text: str) -> str:
    """Convert *bold* and _italic_ markers to ANSI for terminal."""
    import re
    text = re.sub(r"\*(.*?)\*", "\033[1m\\1\033[0m", text)
    text = re.sub(r"_(.*?)_",   "\033[3m\\1\033[0m", text)
    return text


def _fmt_header(label: str):
    print(f"\n\033[32m{'─'*60}\033[0m")
    print(f"\033[32m  🤖 Mondy │ {label}\033[0m")
    print(f"\033[32m{'─'*60}\033[0m")


def _send_text(phone, text, **kw):
    _fmt_header("text")
    print(_strip_wa(text))


def _send_buttons(phone, body, buttons, **kw):
    header = kw.get("header", "")
    footer = kw.get("footer", "")
    _fmt_header("buttons")
    if header:
        print(f"\033[1m{header}\033[0m")
    print(_strip_wa(body))
    if footer:
        print(f"\033[2m{footer}\033[0m")
    print()
    for i, b in enumerate(buttons, 1):
        print(f"  [{i}] {b['title']}  (id: {b['id']})")


def _send_list(phone, body, button_label, sections, **kw):
    header = kw.get("header", "")
    footer = kw.get("footer", "")
    _fmt_header("list")
    if header:
        print(f"\033[1m{header}\033[0m")
    print(_strip_wa(body))
    if footer:
        print(f"\033[2m{footer}\033[0m")
    print()
    row_num = 1
    for sec in sections:
        print(f"  ── {sec['title']} ──")
        for row in sec["rows"]:
            desc = f"  {row.get('description','')}" if row.get("description") else ""
            print(f"  [{row_num}] {row['title']}{desc}  (id: {row['id']})")
            row_num += 1
    print(f"\n  (tap '{button_label}' on phone)")


def _send_image(*a, **kw):
    _fmt_header("image")
    print(f"  [image would be sent here: {kw.get('caption','')}]")


# Build the fake whatsapp module
_wa_mod = types.ModuleType("whatsapp")
_wa_mod.send_text    = _send_text
_wa_mod.send_buttons = _send_buttons
_wa_mod.send_list    = _send_list
_wa_mod.send_image   = _send_image
sys.modules["whatsapp"] = _wa_mod

# Now import bot (it will use our patched whatsapp)
import bot  # noqa: E402  (import after patch is intentional)


# ── Helpers ───────────────────────────────────────────────────────────────────

RESET_CMDS = {"reset", "restart", "clear", "/reset"}


def _resolve_selection(raw: str, last_message) -> str:
    """
    If the user typed a number (e.g. "2") AND the last bot message was a
    list or button prompt, resolve it to the corresponding button/row id.
    """
    if not raw.strip().isdigit():
        return raw.strip()

    idx = int(raw.strip()) - 1  # 0-based

    if last_message is None:
        return raw.strip()

    kind, payload = last_message

    if kind == "buttons":
        buttons = payload
        if 0 <= idx < len(buttons):
            return buttons[idx]["id"]
    elif kind == "list":
        rows = payload
        if 0 <= idx < len(rows):
            return rows[idx]["id"]

    return raw.strip()


# ── Intercept send calls to track last interactive message ────────────────────

_last_interactive: list = [None]   # [0] = (kind, items)


_orig_buttons = _send_buttons
_orig_list    = _send_list


def _track_buttons(phone, body, buttons, **kw):
    _orig_buttons(phone, body, buttons, **kw)
    _last_interactive[0] = ("buttons", buttons)


def _track_list(phone, body, button_label, sections, **kw):
    _orig_list(phone, body, button_label, sections, **kw)
    all_rows = [r for sec in sections for r in sec["rows"]]
    _last_interactive[0] = ("list", all_rows)


_wa_mod.send_buttons = _track_buttons
_wa_mod.send_list    = _track_list


# ── Main REPL ─────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Mondys Organic Farm bot simulator")
    ap.add_argument("--phone", default="911234567890",
                    help="Simulated sender phone number (default: 911234567890)")
    args = ap.parse_args()

    PHONE = args.phone

    print("\n" + "="*60)
    print("  🌿 Mondys Organic Farm — WhatsApp Bot Simulator")
    print("="*60)
    print(f"  Simulated phone: {PHONE}")
    print("  Commands: 'reset' to restart session, Ctrl+C to quit")
    print("  Tip: type a number to pick from a list/button menu")
    print("="*60 + "\n")

    # Kick off the welcome message
    bot.handle_message(PHONE, "text", "hi")

    while True:
        try:
            raw = input("\n\033[33mYou:\033[0m ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\nBye! 👋")
            break

        if not raw:
            continue

        if raw.lower() in RESET_CMDS:
            if PHONE in bot.SESSIONS:
                del bot.SESSIONS[PHONE]
            print("\n\033[90m[session reset]\033[0m")
            bot.handle_message(PHONE, "text", "hi")
            _last_interactive[0] = None
            continue

        resolved = _resolve_selection(raw, _last_interactive[0])
        if resolved != raw:
            print(f"\033[90m  → resolved to: {resolved}\033[0m")

        # If user picked from a list/button, treat as interactive
        msg_type = "interactive" if (resolved != raw) else "text"
        _last_interactive[0] = None   # clear before each call
        bot.handle_message(PHONE, msg_type, resolved)


if __name__ == "__main__":
    main()
