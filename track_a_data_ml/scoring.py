"""
Composite safety scoring engine. Combines OSM, vision, transit and incident
features into one 0-100 score per route, with persona-based weights and a
time-of-day adjustment. Returns the full factor breakdown -- exposing the
"why" behind the number is the actual point of SafeRoute.
"""
from config import PERSONA_WEIGHTS


def time_of_day_factor(hour: int) -> float:
    """0-1 multiplier applied to crowd & business scores -- fewer people
    around and more shut businesses late at night, even if the raw data
    (e.g. a mocked demo route) doesn't already reflect that."""
    if 6 <= hour < 18:
        return 1.0
    if 18 <= hour < 21:
        return 0.85
    return 0.55


def score_route(features: dict, persona: str = "default", hour: int = 12) -> dict:
    """
    features expects normalized 0-1 values, already oriented so that
    HIGHER = SAFER for every key:
      lighting, crowd, business, transit, incident, isolation
    """
    weights = PERSONA_WEIGHTS.get(persona, PERSONA_WEIGHTS["default"])
    tod = time_of_day_factor(hour)

    adjusted = dict(features)
    adjusted["crowd"] = features.get("crowd", 0.5) * tod
    adjusted["business"] = features.get("business", 0.5) * tod

    breakdown = {}
    total = 0.0
    for factor, weight in weights.items():
        value = adjusted.get(factor, 0.5)
        contribution = value * weight
        breakdown[factor] = {
            "value": round(value, 3),
            "weight": weight,
            "contribution": round(contribution, 3),
        }
        total += contribution

    return {
        "score": round(total * 100, 1),
        "persona": persona,
        "hour": hour,
        "breakdown": breakdown,
    }
