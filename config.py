import os
from dotenv import load_dotenv
from datetime import date as _date

load_dotenv()

# ── WhatsApp ──────────────────────────────────────────────────────────────────
WHATSAPP_TOKEN  = os.environ["WHATSAPP_TOKEN"]
PHONE_NUMBER_ID = os.environ["PHONE_NUMBER_ID"]
VERIFY_TOKEN    = os.environ["VERIFY_TOKEN"]
PORT            = int(os.getenv("PORT", 5000))

# ── Property ──────────────────────────────────────────────────────────────────
PROPERTY_NAME    = os.getenv("PROPERTY_NAME",    "Farmhouse Goa")
PROPERTY_ADDRESS = os.getenv("PROPERTY_ADDRESS", "Farmhouse Road, South Goa, 403702")
PROPERTY_GPS     = os.getenv("PROPERTY_GPS",     "https://maps.google.com/?q=15.3173,74.0837")
PROPERTY_CONTACT = os.getenv("PROPERTY_CONTACT", "+91-XXXXXXXXXX")

# ── Facilities ────────────────────────────────────────────────────────────────
FACILITIES = {
    "TV":             os.getenv("FAC_TV",       "Yes — in all rooms"),
    "AC":             os.getenv("FAC_AC",       "Yes — in all rooms"),
    "Geyser":         os.getenv("FAC_GEYSER",   "Yes — all bathrooms"),
    "WiFi":           os.getenv("FAC_WIFI",     "Yes — high-speed broadband"),
    "Meals":          os.getenv("FAC_MEALS",    "Yes — BLD available on request"),
    "Drinking Water": os.getenv("FAC_WATER",    "Yes — RO purified water"),
    "Power Backup":   os.getenv("FAC_POWER",    "Yes — diesel generator"),
    "Toiletry Kit":   os.getenv("FAC_TOILETRY", "Yes — complimentary"),
    "Laundry":        os.getenv("FAC_LAUNDRY",  "Yes — on request (₹100/load)"),
    "Caretaker":      os.getenv("FAC_CARETAKER","Yes — 24/7 on premises"),
    "Cook":           os.getenv("FAC_COOK",     "Yes — on request"),
    "Swimming Pool":  os.getenv("FAC_POOL",     "Yes — seasonal (Oct–May)"),
    "Bonfire Area":   os.getenv("FAC_BONFIRE",  "Yes — on request"),
    "Parking":        os.getenv("FAC_PARKING",  "Yes — ample free parking"),
}

# ── Room Details ──────────────────────────────────────────────────────────────
ROOM_DETAILS = [
    {"name": "Room 1", "type": "Deluxe",   "bathroom": "Attached • Western",       "ac": True,  "tv": True,  "pax": 3, "rate": 3000},
    {"name": "Room 2", "type": "Deluxe",   "bathroom": "Attached • Western",       "ac": True,  "tv": True,  "pax": 3, "rate": 3000},
    {"name": "Room 3", "type": "Standard", "bathroom": "Attached • Western",       "ac": True,  "tv": True,  "pax": 3, "rate": 2500},
    {"name": "Room 4", "type": "Standard", "bathroom": "Shared • Indian + Western","ac": False, "tv": False, "pax": 3, "rate": 2000},
]
TOTAL_ROOMS = len(ROOM_DETAILS)

# ── Policies ──────────────────────────────────────────────────────────────────
CHECK_IN_TIME    = os.getenv("CHECK_IN_TIME",   "12:00 PM")
CHECK_OUT_TIME   = os.getenv("CHECK_OUT_TIME",  "11:00 AM")
NOISE_POLICY     = os.getenv("NOISE_POLICY",    "Quiet hours 10 PM – 7 AM. No loud music after 10 PM. Bonfire by midnight.")
PET_POLICY       = os.getenv("PET_POLICY",      "Pets allowed (small/medium dogs only). Please inform in advance.")
CHILD_POLICY     = os.getenv("CHILD_POLICY",    "Children warmly welcome! Kids' zone, animal feeding & supervised walks available.")
SENIOR_POLICY    = os.getenv("SENIOR_POLICY",   "Senior-friendly: ground-floor rooms on request, ramps & 24/7 caretaker.")
DISABLED_POLICY  = os.getenv("DISABLED_POLICY", "Wheelchair-accessible rooms on request. Please mention at booking.")
EXTRA_PERSON_FEE = int(os.getenv("EXTRA_PERSON_FEE", "500"))

# ── Medical ───────────────────────────────────────────────────────────────────
NEAREST_HOSPITAL = os.getenv("NEAREST_HOSPITAL", "Hospicio Hospital, Margao — 18 km (24/7)")
MEDICAL_CONTACT  = os.getenv("MEDICAL_CONTACT",  "+91-832-2705664")
AMBULANCE        = os.getenv("AMBULANCE",         "108 (free national ambulance)")
PHARMACY_INFO    = os.getenv("PHARMACY_INFO",     "Pharmacy 3 km away. First-aid kit on premises.")

# ── Transport Contacts ────────────────────────────────────────────────────────
TRANSPORT_CONTACT    = os.getenv("TRANSPORT_CONTACT",    "+91-XXXXXXXXXX (Kumar — Driver)")
TOUR_GUIDE_CONTACT   = os.getenv("TOUR_GUIDE_CONTACT",   "+91-XXXXXXXXXX (Raju — Certified Guide)")
SPORTS_GUIDE_CONTACT = os.getenv("SPORTS_GUIDE_CONTACT", "+91-XXXXXXXXXX (Priya — Adventure & Sports)")

# ── Climate by month ──────────────────────────────────────────────────────────
CLIMATE_BY_MONTH = {
    1:  "☀️ Cool & dry ~25°C. Best sightseeing weather. Light jacket for evenings.",
    2:  "☀️ Warm & pleasant ~27°C. Great beach weather. Sunscreen recommended.",
    3:  "🌡️ Hot ~31°C. Morning activities preferred. Light cottons & hat essential.",
    4:  "🌡️ Very hot ~34°C. Avoid midday outdoors. Carry ORS & lots of water.",
    5:  "🌦️ Hot & humid ~33°C. Pre-monsoon showers. Umbrella handy.",
    6:  "🌧️ Monsoon begins ~28°C. Heavy rains. Waterproof gear essential.",
    7:  "🌧️ Peak monsoon ~27°C. Lush greenery & waterfalls. Rain gear mandatory.",
    8:  "🌧️ Monsoon ~27°C. Waterfalls at peak. Waterproof shoes a must.",
    9:  "🌦️ Late monsoon ~28°C. Occasional showers. Good for nature & birdwatching.",
    10: "🌤️ Post-monsoon ~29°C. Fresh landscapes. All activities open. Excellent!",
    11: "☀️ Pleasant & festive ~28°C. Festival season — book early!",
    12: "☀️ Cool & festive ~26°C. Peak season. High demand — advance booking advised.",
}

# ── Things to carry ───────────────────────────────────────────────────────────
THINGS_TO_CARRY = [
    "🔦 Torch / Flashlight (night walks)",
    "🦟 Mosquito repellent — cream or spray",
    "👟 Comfortable walking / trekking shoes",
    "🥾 Gumboots if visiting Jun–Sep",
    "🧢 Cap / Hat + sunglasses",
    "☂️ Umbrella or rain poncho",
    "🕶️ Sunscreen SPF 50+",
    "💊 Personal medication & allergy details",
    "🪪 Govt. Photo ID (mandatory at check-in)",
    "💧 Reusable water bottle",
    "📷 Camera — great photography spots!",
]

# ── Payment info ──────────────────────────────────────────────────────────────
PAYMENT_INFO = (
    "💳 *Payment Methods Accepted*\n"
    "  ✅ UPI / QR Code\n"
    "  ✅ NEFT / Bank Transfer\n"
    "  ✅ Credit Card (Visa/MC/RuPay)\n"
    "  ✅ Debit Card\n"
    "  ✅ Cash on arrival\n\n"
    "_Advance: 50% at booking. Balance: at check-in._"
)
