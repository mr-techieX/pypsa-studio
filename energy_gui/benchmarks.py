"""Deterministic synthetic development cases, never represented as measured grids."""

import math

from .project import Project


def stage3_grid():
    """14 buses / 24 hours: ring, LV transformer, heat conversion and battery."""
    project = Project(name="Stage 3 synthetic grid acceptance")
    project.set_horizon("2026-01-01", 24, 60)
    for carrier in ["AC", "heat", "grid", "wind", "battery"]:
        project.upsert("Carrier", carrier, {})
    for i in range(12):
        project.upsert("Bus", f"B{i:02}", {"v_nom": 220, "carrier": "AC"})
        project.upsert("Line", f"L{i:02}", {
            "bus0": f"B{i:02}", "bus1": f"B{(i+1)%12:02}", "x": 10, "r": 0.5, "s_nom": 150,
        })
    project.upsert("Bus", "LV", {"v_nom": 110, "carrier": "AC"})
    project.upsert("Bus", "Heat", {"carrier": "heat"})
    project.upsert("Transformer", "T", {"bus0": "B06", "bus1": "LV", "s_nom": 20, "x": 0.1, "r": 0.01})
    for name, bus, capacity, cost, carrier in [
        ("Grid", "B00", 150, 10, "grid"), ("Backup", "B06", 200, 150, "grid"),
        ("Wind", "B09", 40, 0, "wind"),
    ]:
        project.upsert("Generator", name, {"bus": bus, "p_nom": capacity, "marginal_cost": cost, "carrier": carrier})
    for i in range(1, 12):
        project.upsert("Load", f"Demand{i:02}", {"bus": f"B{i:02}", "p_set": 5})
    project.upsert("Load", "LV demand", {"bus": "LV", "p_set": 8})
    project.upsert("Load", "Heat demand", {"bus": "Heat", "p_set": 9})
    project.upsert("Link", "Heat pump", {"bus0": "B03", "bus1": "Heat", "p_nom": 10, "efficiency": 3})
    project.upsert("StorageUnit", "Battery", {
        "bus": "B04", "carrier": "battery", "p_nom": 15, "max_hours": 3,
        "efficiency_store": 0.9, "efficiency_dispatch": 0.9, "cyclic_state_of_charge": True,
    })
    project.profiles = [
        {"component": "Generator", "name": "Grid", "attribute": "marginal_cost", "values": [10]*8+[60]*8+[100]*8, "source": "synthetic", "unit": "currency/MWh"},
        {"component": "Generator", "name": "Wind", "attribute": "p_max_pu", "values": [max(0, math.sin((h-6)*math.pi/12)) for h in range(24)], "source": "synthetic", "unit": "per unit"},
    ]
    return project
