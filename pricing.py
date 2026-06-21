"""
pricing.py — total-cost calculation.

All rates/meal-plans/activities/pickup-points/vehicles now live in the database
(seeded from defaults on first run, edited via the admin dashboard). The legacy
module-level constants are kept as thin wrappers for any code that still imports
them (e.g. older parts of the WhatsApp info flow), but they read live from DB.
"""
import database


# ── Live read-throughs ───────────────────────────────────────────────────────

def _rooms_map() -> dict:
    return {r["name"]: r for r in database.list_rooms()}


def _meals_map() -> dict:
    return {m["name"]: m for m in database.list_meal_plans()}


def _activities_map(day: str) -> dict:
    return {a["name"]: a for a in database.list_activities(day=day)}


def _pickup_map() -> dict:
    return {p["name"]: p for p in database.list_pickup_points()}


def _vehicle_map() -> dict:
    return {v["name"]: v for v in database.list_vehicle_types()}


# ── Activity cost helper ─────────────────────────────────────────────────────

def _activity_cost(activities, day: str, pax: int) -> int:
    """activities can be list[str] (legacy) or dict {name: count}."""
    amap = _activities_map(day)
    total = 0
    items = activities.items() if isinstance(activities, dict) else [(a, pax) for a in activities]
    for name, count in items:
        info = amap.get(name, {})
        price = info.get("price", 0)
        per = info.get("per_unit", "group")
        total += price * count if per in ("person", "head", "boat") else price
    return total


# ── Main calculator ─────────────────────────────────────────────────────────

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
    rooms = _rooms_map()
    meals = _meals_map()
    pickups = _pickup_map()
    vehicles = _vehicle_map()

    room_rate = rooms.get(room_type, {}).get("rate", 0)
    room_cost = room_rate * nights * room_count

    meal_d1_cost = meals.get(meal_plan_d1, {}).get("price", 0) * pax
    meal_sub_cost = meals.get(meal_plan_sub, {}).get("price", 0) * pax * max(nights - 1, 0)
    meal_cost = meal_d1_cost + meal_sub_cost

    act_cost = _activity_cost(activities_d1, "d1", pax) + _activity_cost(activities_d2, "d2", pax)

    base_transport = pickups.get(pickup_point, {}).get("base_fare", 0) if pickup_point else 0
    veh_mult = vehicles.get(vehicle_type, {}).get("multiplier", 1.0) if vehicle_type else 1.0
    transport_cost = round(base_transport * veh_mult)

    return {
        "room":       room_cost,
        "meals":      meal_cost,
        "activities": act_cost,
        "transport":  transport_cost,
        "total":      room_cost + meal_cost + act_cost + transport_cost,
    }


# ── Legacy constant facades (some bot.py info functions still reference these) ─

def _legacy_room_rates() -> dict:
    return {r["name"]: r["rate"] for r in database.list_rooms()}


def _legacy_room_inventory() -> dict:
    return {r["name"]: r["inventory"] for r in database.list_rooms()}


def _legacy_meal_combos() -> dict:
    return {m["name"]: m["price"] for m in database.list_meal_plans()}


def _legacy_pickup_points() -> dict:
    return {p["name"]: p["base_fare"] for p in database.list_pickup_points()}


# Per-meal prices (BLD components) — kept hardcoded for display only.
MEAL_PRICES = {
    "Breakfast": 200,
    "Lunch":     350,
    "Dinner":    400,
}


# Module-level attributes for legacy callers. They look like dicts but
# re-fetch on each attribute access via __getattr__.
def __getattr__(name):
    if name == "ROOM_RATES":     return _legacy_room_rates()
    if name == "ROOM_INVENTORY": return _legacy_room_inventory()
    if name == "MEAL_COMBOS":    return _legacy_meal_combos()
    if name == "PICKUP_POINTS":  return _legacy_pickup_points()
    if name == "ROOM_PAX_LIMIT": return {r["name"]: r["capacity"] for r in database.list_rooms()}
    if name == "ACTIVITIES_D1":
        return {a["name"]: {"price": a["price"], "per": a["per_unit"], "duration": a["duration"], "free": a["is_free"], "note": a["note"]}
                for a in database.list_activities(day="d1")}
    if name == "ACTIVITIES_D2":
        return {a["name"]: {"price": a["price"], "per": a["per_unit"], "duration": a["duration"], "free": a["is_free"], "note": a["note"]}
                for a in database.list_activities(day="d2")}
    if name == "VEHICLE_TYPES":
        return {v["name"]: {"desc": v["description"], "multiplier": v["multiplier"]} for v in database.list_vehicle_types()}
    raise AttributeError(name)
