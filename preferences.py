"""
Preference engine: data model, state machine, validation, and completion tracking.

The voice agent extracts preferences from conversation and emits them as
structured client_actions. This module stores, validates, and exposes them
for the booking teammate's code.
"""
from __future__ import annotations

import time
from threading import Lock
from typing import Any

CATEGORIES = ("trip", "flight", "hotel", "food")

FIELD_SCHEMA: dict[str, dict[str, dict[str, Any]]] = {
    "trip": {
        "origin": {"type": "string", "required": True},
        "destination": {"type": "string", "required": True},
        "departure_date": {"type": "string", "required": True},
        "return_date": {"type": "string", "required": False},
        "trip_type": {"type": "string", "valid": ["one_way", "round_trip", "multi_city"], "required": False},
        "number_of_travelers": {"type": "int", "required": True},
        "has_toddler": {"type": "boolean", "required": False},
        "trip_purpose": {"type": "string", "valid": ["business", "leisure", "family", "honeymoon"], "required": False},
    },
    "flight": {
        "stops": {"type": "string", "valid": ["nonstop", "1_stop", "any"], "required": False},
        "max_budget": {"type": "number", "required": False},
        "preferred_time": {"type": "string", "valid": ["early_morning", "morning", "afternoon", "evening", "red_eye"], "required": False},
        "seat_type": {"type": "string", "valid": ["window", "aisle", "middle", "no_preference"], "required": False},
        "cabin_class": {"type": "string", "valid": ["economy", "premium_economy", "business", "first"], "required": False},
        "airline_preference": {"type": "string", "required": False},
        "needs_bassinet": {"type": "boolean", "required": False},
    },
    "hotel": {
        "room_type": {"type": "string", "valid": ["single", "double", "suite", "family", "connecting"], "required": False},
        "max_budget_per_night": {"type": "number", "required": False},
        "star_rating": {"type": "int", "required": False},
        "amenities": {"type": "array", "required": False},
        "location_preference": {"type": "string", "required": False},
        "needs_crib": {"type": "boolean", "required": False},
    },
    "food": {
        "diet_type": {"type": "string", "valid": ["veg", "non_veg", "vegan", "no_preference"], "required": False},
        "cuisine_preference": {"type": "array", "required": False},
        "allergies": {"type": "array", "required": False},
    },
}

REQUIRED_FOR_READY = [
    ("trip", "origin"),
    ("trip", "destination"),
    ("trip", "departure_date"),
    ("trip", "return_date"),
    ("trip", "number_of_travelers"),
    ("trip", "trip_purpose"),
]


def _empty_preferences() -> dict:
    prefs = {}
    for category, fields in FIELD_SCHEMA.items():
        prefs[category] = {field: None for field in fields}
    return prefs


class PreferenceStore:
    """Thread-safe single-session preference store with state machine."""

    def __init__(self):
        self._lock = Lock()
        self._preferences: dict = _empty_preferences()
        self._status: str = "empty"
        self._history: list[dict] = []
        self._last_updated: float | None = None
        self._confirmed: bool = False

    def get_all(self) -> dict:
        with self._lock:
            return {
                "preferences": self._preferences.copy(),
                "status": self._status,
                "completion": self._completion(),
                "confirmed": self._confirmed,
                "last_updated": self._last_updated,
                "history": self._history[-20:],
            }

    def update(self, category: str, field: str, value: Any) -> dict:
        with self._lock:
            if category not in CATEGORIES:
                return {"ok": False, "error": f"Invalid category: {category}"}
            if field not in FIELD_SCHEMA.get(category, {}):
                return {"ok": False, "error": f"Invalid field: {category}.{field}"}

            previous_value = self._preferences[category][field]
            is_change = previous_value is not None and previous_value != value

            self._preferences[category][field] = value
            self._last_updated = time.time()

            self._history.append({
                "category": category,
                "field": field,
                "value": value,
                "previous_value": previous_value,
                "is_change": is_change,
                "timestamp": self._last_updated,
            })

            if self._confirmed and is_change:
                self._confirmed = False
                self._status = "invalidated"
            elif self._status == "confirmed" and is_change:
                self._status = "invalidated"
            elif self._status in ("empty", "collecting", "invalidated"):
                if self._is_ready():
                    self._status = "recommendations_ready"
                else:
                    self._status = "collecting"

            return {
                "ok": True,
                "is_change": is_change,
                "previous_value": previous_value,
                "preferences": self._preferences.copy(),
                "status": self._status,
                "completion": self._completion(),
            }

    def confirm(self) -> dict:
        with self._lock:
            if not self._is_ready():
                return {"ok": False, "error": "Missing required preferences", "status": self._status}
            self._confirmed = True
            self._status = "confirmed"
            return {
                "ok": True,
                "status": "confirmed",
                "preferences": self._preferences.copy(),
            }

    def mark_ready(self) -> dict:
        with self._lock:
            self._status = "recommendations_ready"
            return {"ok": True, "status": self._status}

    def invalidate(self, reason: str = "") -> dict:
        with self._lock:
            self._status = "invalidated"
            self._confirmed = False
            return {"ok": True, "status": self._status, "reason": reason}

    def reset(self) -> dict:
        with self._lock:
            self._preferences = _empty_preferences()
            self._status = "empty"
            self._history = []
            self._last_updated = None
            self._confirmed = False
            return {"ok": True, "status": "empty"}

    def _is_ready(self) -> bool:
        for category, field in REQUIRED_FOR_READY:
            if self._preferences[category][field] is None:
                return False
        return True

    def _completion(self) -> float:
        total = 0
        filled = 0
        for category, fields in FIELD_SCHEMA.items():
            for field in fields:
                total += 1
                if self._preferences[category][field] is not None:
                    filled += 1
        return round(filled / total, 2) if total > 0 else 0.0
