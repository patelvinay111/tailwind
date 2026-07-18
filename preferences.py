"""
Traveler Persona — persistent preferences used across all bookings and rebookings.

These are NOT trip-specific (no origin/destination/dates). They represent the
traveler's personal style and needs that apply to every trip they take.

The voice agent collects these once, saves them as a persona, and they're
automatically applied whenever we search for flights, hotels, or restaurants.
"""
from __future__ import annotations

import json
import os
import time
from threading import Lock
from typing import Any

PERSONA_FILE = os.path.join(os.path.dirname(__file__), "traveler_persona.json")

CATEGORIES = ("traveler", "flight", "hotel", "food")

FIELD_SCHEMA: dict[str, dict[str, dict[str, Any]]] = {
    "traveler": {
        "name": {"type": "string", "required": False},
        "number_of_travelers": {"type": "int", "required": False},
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
    },
    "food": {
        "diet_type": {"type": "string", "valid": ["veg", "non_veg", "vegan", "no_preference"], "required": False},
        "allergies": {"type": "array", "required": False},
    },
}

REQUIRED_FOR_READY = [
    ("flight", "seat_type"),
    ("flight", "cabin_class"),
    ("food", "diet_type"),
]


def _empty_preferences() -> dict:
    prefs = {}
    for category, fields in FIELD_SCHEMA.items():
        prefs[category] = {field: None for field in fields}
    return prefs


class PreferenceStore:
    """Thread-safe traveler persona store. Persists to disk as JSON."""

    def __init__(self):
        self._lock = Lock()
        self._preferences: dict = _empty_preferences()
        self._status: str = "empty"
        self._history: list[dict] = []
        self._last_updated: float | None = None
        self._confirmed: bool = False
        self._load_from_disk()

    def _load_from_disk(self):
        """Load saved persona if it exists."""
        if os.path.exists(PERSONA_FILE):
            try:
                with open(PERSONA_FILE, "r") as f:
                    saved = json.load(f)
                for category in CATEGORIES:
                    if category in saved:
                        for field, value in saved[category].items():
                            if field in self._preferences.get(category, {}):
                                self._preferences[category][field] = value
                self._status = "complete" if self._is_ready() else "collecting"
                self._confirmed = self._is_ready()
            except (json.JSONDecodeError, KeyError):
                pass

    def _save_to_disk(self):
        """Persist persona to disk."""
        with open(PERSONA_FILE, "w") as f:
            json.dump(self._preferences, f, indent=2)

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

    def get_for_booking(self) -> dict:
        """Return preferences in a format useful for booking/search APIs."""
        with self._lock:
            return {
                "traveler": self._preferences["traveler"],
                "flight_preferences": self._preferences["flight"],
                "hotel_preferences": self._preferences["hotel"],
                "food_preferences": self._preferences["food"],
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

            if self._is_ready():
                self._status = "complete"
            else:
                self._status = "collecting"

            self._save_to_disk()

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
            self._confirmed = True
            self._status = "complete"
            self._save_to_disk()
            return {
                "ok": True,
                "status": "complete",
                "preferences": self._preferences.copy(),
            }

    def reset(self) -> dict:
        with self._lock:
            self._preferences = _empty_preferences()
            self._status = "empty"
            self._history = []
            self._last_updated = None
            self._confirmed = False
            if os.path.exists(PERSONA_FILE):
                os.remove(PERSONA_FILE)
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
