"""Explicitly synthetic three-bus example; not a real Odisha asset inventory."""

import math

from .project import Project


def demo_project():
    project = Project(name="Three-node dispatch lab", currency="INR")
    project.set_horizon("2026-01-01 00:00", 24, 60)
    for name, color in [("AC", "#64d5c2"), ("coal", "#f1b97a"), ("solar", "#ffcf66")]:
        project.upsert("Carrier", name, {"color": color})
    for name, x, y in [("North", 0, 1), ("Central", 1, 0), ("City", 2, 1)]:
        project.upsert("Bus", name, {"v_nom": 220, "carrier": "AC", "x": x, "y": y})
    project.upsert("Generator", "Thermal", {"bus": "North", "carrier": "coal", "p_nom": 150, "marginal_cost": 2500})
    project.upsert("Generator", "Solar", {"bus": "Central", "carrier": "solar", "p_nom": 80, "marginal_cost": 0})
    project.upsert("Generator", "City peaker", {"bus": "City", "carrier": "coal", "p_nom": 90, "marginal_cost": 6000})
    project.upsert("Load", "City demand", {"bus": "City", "p_set": 100})
    for name, a, b, cap in [("North–Central", "North", "Central", 100), ("Central–City", "Central", "City", 85), ("North–City", "North", "City", 50)]:
        project.upsert("Line", name, {"bus0": a, "bus1": b, "x": 10, "r": 0.5, "s_nom": cap})
    project.profiles = [
        {"component": "Load", "name": "City demand", "attribute": "p_set", "values": [100 + 20 * math.cos((h - 19) * math.pi / 12) for h in range(24)], "source": "synthetic example", "unit": "MW"},
        {"component": "Generator", "name": "Solar", "attribute": "p_max_pu", "values": [max(0, math.sin((h - 6) * math.pi / 12)) for h in range(24)], "source": "synthetic example", "unit": "per unit"},
    ]
    return project
