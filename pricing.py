from datetime import date as _date

# ── Base room rates ───────────────────────────────────────────────────────────
ROOM_PRICE_COUPLE = 3000   # per night (1 room)
ROOM_PRICE_BULK   = 2500   # per room per night

# ── Seasonal multipliers ──────────────────────────────────────────────────────
PEAK_MONTHS = {11, 12, 1, 2}   # Nov–Feb  +30 %
OFF_MONTHS  = {6, 7, 8, 9}     # Jun–Sep  −15 %

# ── Meal plans (per person per night) ────────────────────────────────────────
MEAL_PLAN = {
    "No Meals":           0,
    "Breakfast Only":   200,
    "Lunch Only":       350,
    "Dinner Only":      400,
    "Breakfast+Dinner": 550,
    "All Meals (BLD)":  900,
}

# ── Activities (per person unless marked *group*) ─────────────────────────────
ACTIVITIES = {
    # Farm
    "Veg/Fruit Picking":  150,
    "Animal Petting":     150,
    "Feeding Animals":    100,
    "Guided Farm Tour":   200,
    "Kids Activity Zone": 150,
    # Outdoor / adventure
    "City Tour":          500,
    "Kayaking":           400,
    "Beach Enjoy":        300,
    "Hiking":             200,
    "Fruit Tour":         250,
    "Bonfire Evening":    300,   # per group (charged ×1 regardless of pax)
    "Swimming (Pool)":    200,
}

BONFIRE_PER_GROUP = {"Bonfire Evening"}   # flat rate, not multiplied by pax

# ── Games — all complimentary ─────────────────────────────────────────────────
GAMES_FREE = ["Cricket", "Badminton", "Volleyball", "Carrom", "Chess/Ludo", "Table Tennis"]

# ── Pickup / drop transport ───────────────────────────────────────────────────
TRANSPORT = {
    "Kudal Station":          500,
    "Kankawali Station":      600,
    "Mopa Airport (GOX)":     800,
    "Goa Airport – Dabolim": 1200,
}

# ── Internal / local transport (per day) ─────────────────────────────────────
INTERNAL_TRANSPORT = {
    "Scooter / 2-Wheeler":   400,
    "Hatchback (4-seater)": 1200,
    "SUV (6–7 seater)":     1800,
}

# ── Extra person ─────────────────────────────────────────────────────────────
EXTRA_PERSON_PER_NIGHT = 500   # above 3/room


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_seasonal_multiplier(month: int) -> float:
    if month in PEAK_MONTHS:
        return 1.30
    if month in OFF_MONTHS:
        return 0.85
    return 1.0


def seasonal_label(month: int) -> str:
    m = get_seasonal_multiplier(month)
    if m > 1:
        return "🔴 Peak season (+30%)"
    if m < 1:
        return "🟢 Off-season (−15%)"
    return "🟡 Regular season"


def calculate_total(
    pax:                 int,
    rooms:               int,
    nights:              int,
    room_type:           str,
    selected_activities: list,
    transport_port:      "str | None",
    meal_plan:           str = "No Meals",
    internal_transport:  "str | None" = None,
    check_in_month:      int = 0,
) -> dict:
    if check_in_month == 0:
        check_in_month = _date.today().month

    mult = get_seasonal_multiplier(check_in_month)

    if room_type == "couple":
        room_cost = round(ROOM_PRICE_COUPLE * nights * mult)
    else:
        room_cost = round(ROOM_PRICE_BULK * rooms * nights * mult)

    activity_cost = sum(
        ACTIVITIES.get(a, 0) if a not in BONFIRE_PER_GROUP else ACTIVITIES.get(a, 0)
        for a in selected_activities
    )
    # Bonfire is per group; others are per pax
    for a in selected_activities:
        if a not in BONFIRE_PER_GROUP:
            activity_cost += ACTIVITIES.get(a, 0) * (pax - 1)   # already counted ×1 above

    # Recalculate cleanly
    activity_cost = 0
    for a in selected_activities:
        if a in BONFIRE_PER_GROUP:
            activity_cost += ACTIVITIES.get(a, 0)
        else:
            activity_cost += ACTIVITIES.get(a, 0) * pax

    transport_cost     = TRANSPORT.get(transport_port, 0) if transport_port else 0
    meal_cost          = MEAL_PLAN.get(meal_plan, 0) * pax * nights
    int_transport_cost = INTERNAL_TRANSPORT.get(internal_transport, 0) * nights if internal_transport else 0

    return {
        "room":               room_cost,
        "activities":         activity_cost,
        "transport":          transport_cost,
        "meals":              meal_cost,
        "internal_transport": int_transport_cost,
        "seasonal_note":      seasonal_label(check_in_month),
        "total":              room_cost + activity_cost + transport_cost + meal_cost + int_transport_cost,
    }
