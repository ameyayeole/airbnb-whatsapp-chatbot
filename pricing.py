# ── Room rates (per night) ────────────────────────────────────────────────────
ROOM_RATES = {
    "Family Suite":   6000,   # up to 4 pax
    "Dormitory Stay": 4000,   # up to 6 pax
}
ROOM_PAX_LIMIT = {
    "Family Suite":   4,
    "Dormitory Stay": 6,
}

# Total rooms available of each type at the property
ROOM_INVENTORY = {
    "Family Suite":   2,
    "Dormitory Stay": 2,
}

# ── Meal prices (per person per meal) ─────────────────────────────────────────
MEAL_PRICES = {
    "Breakfast": 200,
    "Lunch":     350,
    "Dinner":    400,
}

MEAL_COMBOS = {
    "All Meals (BLD)":   950,   # 200+350+400
    "Breakfast+Dinner":  600,   # 200+400
    "Lunch+Dinner":      750,   # 350+400
    "Breakfast Only":    200,
    "Dinner Only":       400,
    "No Meals":            0,
}

# ── Day 1 Activities (on-farm) ────────────────────────────────────────────────
ACTIVITIES_D1 = {
    "Animal Petting":            {"price": 0,   "per": "group", "duration": "1 hour",    "free": True},
    "Bullock Cart Ride":         {"price": 100, "per": "person","duration": "15 mins",   "free": False},
    "Pick Your Breakfast Plate": {"price": 300, "per": "person","duration": "30 mins",   "free": False},
    "Trekking":                  {"price": 0,   "per": "group", "duration": "2 hours",   "free": True},
    "Swimming Pool":             {"price": 0,   "per": "group", "duration": "All day",   "free": True},
    "Gazebo Rain Dance":         {"price": 150, "per": "person","duration": "2 hours",   "free": False},
    "Indoor Games":              {"price": 150, "per": "person","duration": "3-4 hours", "free": False},
}

# ── Day 2 Activities (off-farm / outdoor) ─────────────────────────────────────
ACTIVITIES_D2 = {
    "Kayaking":                  {"price": 400, "per": "boat",  "duration": "1 hour",  "free": False, "note": ""},
    "Beach & Temple Visit":      {"price": 0,   "per": "group", "duration": "Half day","free": True,  "note": "Transport charges apply"},
    "Malvan Water Sports":       {"price": 0,   "per": "group", "duration": "Half day","free": True,  "note": "Local fare applies"},
    "Vengurla Beach Exploration":{"price": 0,   "per": "group", "duration": "Half day","free": True,  "note": "Transport charges apply"},
}

# ── Pickup points (base cost, one-way) ───────────────────────────────────────
PICKUP_POINTS = {
    "Kudal Railway Station":      500,
    "Sawantwadi Railway Station": 600,
    "Mopa Airport":               800,
    "Chipi Airport":              700,
}

# ── Vehicle multipliers applied on top of pickup base cost ───────────────────
VEHICLE_TYPES = {
    "Sedan":       {"desc": "4-seater car",           "multiplier": 1.0},
    "MUV":         {"desc": "6-7 seater MUV",         "multiplier": 1.5},
    "Charter Bus": {"desc": "Large group (20+ pax)",  "multiplier": 3.0},
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _activity_cost(activities: list, source: dict, pax: int) -> int:
    total = 0
    for name in activities:
        info  = source.get(name, {})
        price = info.get("price", 0)
        per   = info.get("per", "group")
        total += price * pax if per in ("person", "head") else price
    return total


def calculate_total(
    room_type:     str,
    nights:        int,
    pax:           int,
    meal_plan_d1:  str,
    meal_plan_sub: str,
    activities_d1: list,
    activities_d2: list,
    pickup_point:  "str | None",
    vehicle_type:  "str | None",
    room_count:    int = 1,
) -> dict:
    room_cost      = ROOM_RATES.get(room_type, 0) * nights * room_count
    meal_d1_cost   = MEAL_COMBOS.get(meal_plan_d1,  0) * pax
    meal_sub_cost  = MEAL_COMBOS.get(meal_plan_sub, 0) * pax * max(nights - 1, 0)
    meal_cost      = meal_d1_cost + meal_sub_cost
    act_d1_cost    = _activity_cost(activities_d1, ACTIVITIES_D1, pax)
    act_d2_cost    = _activity_cost(activities_d2, ACTIVITIES_D2, pax)
    base_transport = PICKUP_POINTS.get(pickup_point, 0) if pickup_point else 0
    veh_mult       = VEHICLE_TYPES.get(vehicle_type, {}).get("multiplier", 1.0) if vehicle_type else 1.0
    transport_cost = round(base_transport * veh_mult)

    return {
        "room":       room_cost,
        "meals":      meal_cost,
        "activities": act_d1_cost + act_d2_cost,
        "transport":  transport_cost,
        "total":      room_cost + meal_cost + act_d1_cost + act_d2_cost + transport_cost,
    }
