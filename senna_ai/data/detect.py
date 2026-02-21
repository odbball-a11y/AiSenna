from __future__ import annotations

# ═══════════════════════════════════════════════════════════════════════════
# Car Class Detection
# ═══════════════════════════════════════════════════════════════════════════
CAR_CLASS_PATTERNS = [
    ("lmp2",      "LMP2"),
    ("lm p2",     "LMP2"),
    ("lmh",       "Hypercar"),
    ("lmdh",      "Hypercar"),
    ("hypercar",  "Hypercar"),
    ("hyper",     "Hypercar"),
    ("499p",      "Hypercar"),
    ("963",       "Hypercar"),
    ("9x8",       "Hypercar"),
    ("valkyrie",  "Hypercar"),
    ("gtp",       "Hypercar"),
    ("sc63",      "Hypercar"),
    ("007",       "Hypercar"),
    ("gte",       "GTE"),
    ("c8.r",      "GTE"),
    ("rsr gte",   "GTE"),
    ("vantage gte", "GTE"),
    ("m8 gte",    "GTE"),
    ("gt3",       "GT3"),
    ("lmgt3",     "GT3"),
    ("07/gibson", "LMP2"),
    ("oreca 07",  "LMP2"),
    ("lmp1",      "LMP1"),
    ("ts050",     "LMP1"),
    ("r18",       "LMP1"),
    ("919",       "LMP1"),
]

def detect_car_class(car_name: str, vehicle_class: str = "") -> str:
    """Detect normalised car class from car name and/or mVehicleClass field."""
    combined = f"{vehicle_class} {car_name}".lower()
    for pattern, cls in CAR_CLASS_PATTERNS:
        if pattern in combined:
            return cls
    return "Unknown"
