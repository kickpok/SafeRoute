"""
Transforms scoring.py's output into shapes a charting library can consume
directly, so Track C never has to touch the raw breakdown format.

Two shapes are provided:
- to_radar_series()      -> single route, one radar chart
- to_radar_comparison()  -> multiple routes overlaid on one radar chart
                            (matches what Recharts' <RadarChart> and most
                            other charting libs expect out of the box)
"""

# Friendly axis labels -- some are renamed so "higher = better" reads
# naturally on the chart even for factors that are inherently inverted
# (e.g. "incident" is really "incident-free").
AXIS_LABELS = {
    "lighting": "Lighting",
    "crowd": "Crowd",
    "business": "Open businesses",
    "transit": "Transit access",
    "incident": "Incident-free",
    "isolation": "Not isolated",
}


def to_radar_series(result: dict) -> list:
    """
    result: the dict returned by scoring.score_route()
    Returns: [{"axis": "Lighting", "value": 72}, ...]  (value scaled 0-100)
    """
    return [
        {"axis": AXIS_LABELS.get(factor, factor.title()), "value": round(data["value"] * 100, 1)}
        for factor, data in result["breakdown"].items()
    ]


def to_radar_comparison(named_results: dict) -> list:
    """
    named_results: {"Route A": score_route_output, "Route B": score_route_output, ...}
    Returns: [{"axis": "Lighting", "Route A": 72, "Route B": 85}, ...]
    One row per factor, one column per route -- feed straight into a
    multi-series radar chart.
    """
    factors = next(iter(named_results.values()))["breakdown"].keys()
    rows = []
    for factor in factors:
        row = {"axis": AXIS_LABELS.get(factor, factor.title())}
        for route_name, result in named_results.items():
            row[route_name] = round(result["breakdown"][factor]["value"] * 100, 1)
        rows.append(row)
    return rows
