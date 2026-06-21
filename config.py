import os
from dotenv import load_dotenv

load_dotenv()

# ── WhatsApp ──────────────────────────────────────────────────────────────────
WHATSAPP_TOKEN  = os.environ["WHATSAPP_TOKEN"]
PHONE_NUMBER_ID = os.environ["PHONE_NUMBER_ID"]
VERIFY_TOKEN    = os.environ["VERIFY_TOKEN"]
PORT            = int(os.getenv("PORT", 5000))

# Public base URL used to build the booking link sent over WhatsApp.
# Set BASE_URL in .env to your deployed URL (e.g. https://mondys-bot.onrender.com).
BASE_URL        = os.getenv("BASE_URL", f"http://localhost:{PORT}")

# WhatsApp business number for "Book a Stay" CTA on the homepage.
# Format: country-code + number, no symbols (e.g. 919999999999).
WA_BUSINESS_NUMBER = os.getenv("WA_BUSINESS_NUMBER", "919999999999")

# ── Admin dashboard ───────────────────────────────────────────────────────────
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "changeme")
SECRET_KEY     = os.getenv("SECRET_KEY", "dev-secret-change-me")

# Folder where admin-uploaded images (QR + photos) are stored. Served at /uploads/.
UPLOAD_FOLDER  = os.path.join(os.path.dirname(__file__), "uploads")

# ── Property ──────────────────────────────────────────────────────────────────
PROPERTY_NAME    = "Mondkar Farm Stay"
BOT_NAME         = "Mondy"
WEBSITE_URL      = os.getenv("WEBSITE_URL",      "https://mondys.in")
PROPERTY_ADDRESS = os.getenv("PROPERTY_ADDRESS", "Mondys Farm Stay, Sindhudurg, Maharashtra")
PROPERTY_GPS     = os.getenv("PROPERTY_GPS",     "https://maps.google.com/?q=16.0,73.7")
PROPERTY_CONTACT = os.getenv("PROPERTY_CONTACT", "+91-XXXXXXXXXX")
SUPPORT_EMAIL    = os.getenv("SUPPORT_EMAIL",    "stay@mondys.in")

# ── Check-in / out ────────────────────────────────────────────────────────────
CHECK_IN_TIME  = "1:00 PM"
CHECK_OUT_TIME = "12:00 PM (Noon)"

# ── Facilities (for Info menu) ────────────────────────────────────────────────
FACILITIES = {
    "Rooms":          "Family Suite (4 pax) · Dormitory Stay (6 pax)",
    "Bathrooms":      "Attached — Western style",
    "AC":             "Available on request",
    "Meals":          "Veg & Non-Veg — freshly prepared",
    "Swimming Pool":  "Seasonal (complimentary for guests)",
    "WiFi":           "Available in common areas",
    "Parking":        "Free on-site parking",
    "Bonfire/Gazebo": "Available seasonally",
    "Caretaker":      "24/7 on premises",
    "Power Backup":   "Generator available",
}

# ── Policies ──────────────────────────────────────────────────────────────────
CANCELLATION_POLICY = (
    "50% advance at time of booking.\n"
    "50% refund if cancelled 7+ days before check-in.\n"
    "Zero refund within 7 days of check-in.\n"
    "Partial cancellations allowed (by days / rooms / guests)."
)
ADVANCE_PERCENT = 50

# ── Medical ───────────────────────────────────────────────────────────────────
NEAREST_HOSPITAL = os.getenv("NEAREST_HOSPITAL", "District Hospital, Sindhudurg — 12 km")
MEDICAL_CONTACT  = os.getenv("MEDICAL_CONTACT",  "+91-XXXXXXXXXX")
AMBULANCE        = os.getenv("AMBULANCE",         "108 (free national ambulance)")
PHARMACY_INFO    = os.getenv("PHARMACY_INFO",     "Pharmacy 2 km away. First-aid kit on premises.")

# ── Transport contacts ────────────────────────────────────────────────────────
TRANSPORT_CONTACT    = os.getenv("TRANSPORT_CONTACT",    "+91-XXXXXXXXXX (Farm Driver)")
TOUR_GUIDE_CONTACT   = os.getenv("TOUR_GUIDE_CONTACT",   "+91-XXXXXXXXXX (Local Guide)")
SPORTS_GUIDE_CONTACT = os.getenv("SPORTS_GUIDE_CONTACT", "+91-XXXXXXXXXX (Water Sports)")

# ── Climate by month ──────────────────────────────────────────────────────────
CLIMATE_BY_MONTH = {
    1:  "☀️ Cool & dry ~23°C. Perfect for all outdoor activities.",
    2:  "☀️ Warm ~25°C. Ideal for beach, trekking & farm activities.",
    3:  "🌡️ Hot ~30°C. Morning activities recommended. Stay hydrated.",
    4:  "🌡️ Hot ~33°C. Avoid afternoon outdoors. Light clothing essential.",
    5:  "🌦️ Pre-monsoon ~32°C. Occasional showers. Umbrella handy.",
    6:  "🌧️ Monsoon begins ~28°C. Lush green farm. Rain gear needed.",
    7:  "🌧️ Heavy monsoon ~27°C. Waterfalls & green trails. Rain gear mandatory.",
    8:  "🌧️ Peak monsoon ~27°C. Farm at its most lush. Waterproof shoes a must.",
    9:  "🌦️ Late monsoon ~28°C. Farm at its most beautiful!",
    10: "🌤️ Post-monsoon ~29°C. All activities open. Excellent weather.",
    11: "☀️ Pleasant ~27°C. Perfect season — book early!",
    12: "☀️ Cool & festive ~24°C. Peak season. Advance booking advised.",
}

# ── Things to carry ───────────────────────────────────────────────────────────
THINGS_TO_CARRY = [
    "🔦 Torch (for night walks & bonfires)",
    "🦟 Mosquito repellent",
    "👟 Comfortable walking shoes / gumboots (monsoon)",
    "🧢 Cap + sunglasses",
    "☂️ Umbrella or rain poncho",
    "💊 Personal medication",
    "🪪 Govt. Photo ID (mandatory at check-in)",
    "📷 Camera — stunning farm & nature spots!",
    "💧 Reusable water bottle",
]

# ── Payment ───────────────────────────────────────────────────────────────────
PAYMENT_INFO = (
    "💳 *Payment Methods Accepted*\n"
    "  ✅ UPI / QR Code\n"
    "  ✅ Credit / Debit Card\n"
    "  ✅ Cash on arrival\n"
    "  ✅ Bank Transfer\n\n"
    f"_Advance: {ADVANCE_PERCENT}% at booking. Balance: at check-in._"
)
