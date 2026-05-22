ROOM_PRICE_COUPLE = 3000   # per night (placeholder)
ROOM_PRICE_BULK = 2500     # per room per night (placeholder)

ACTIVITIES = {
    "City Tour":   500,
    "Kayaking":    400,
    "Beach Enjoy": 300,
    "Hiking":      200,
    "Fruit Tour":  250,
}

TRANSPORT = {
    "Kudal":        500,
    "Kankawali":    600,
    "Mopa Airport": 800,
}


def calculate_total(pax: int, rooms: int, nights: int,
                    selected_activities: list[str], transport_port: str | None) -> dict:
    if rooms == 1 and transport_port is None:
        room_cost = ROOM_PRICE_COUPLE * nights
    else:
        room_cost = ROOM_PRICE_BULK * rooms * nights

    activity_cost = sum(ACTIVITIES.get(a, 0) for a in selected_activities) * pax
    transport_cost = TRANSPORT.get(transport_port, 0) if transport_port else 0

    return {
        "room": room_cost,
        "activities": activity_cost,
        "transport": transport_cost,
        "total": room_cost + activity_cost + transport_cost,
    }
