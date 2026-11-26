"""Deterministic, use-case-led studies. No random data or online runtime access."""

from copy import deepcopy
import json
import math
from pathlib import Path

from .benchmarks import stage3_grid
from .demo import demo_project
from .network_view import topology
from .project import Project


DEMO_SPECS = [
    dict(id="congestion2", title="2 buses · constrained city import", buses=2, hours=1,
         summary="A cheap remote plant cannot supply the whole city through a 40 MW corridor; a local peaker fills the gap.",
         expected="Cheap plant 40 MW, peaker 20 MW, total cost 2800 USD for one hour. Inspect corridor flow and bus prices.",
         assumptions="Synthetic exact teaching case: 60 MW demand, offers 20/100 USD/MWh, no losses, reserves or outages."),
    dict(id="urban3", title="3 buses · urban solar and thermal dispatch", buses=3, hours=24,
         summary="The original urban-load example: daytime solar, remote thermal generation, a city peaker and three transfer paths.",
         expected="Inspect solar displacement, evening demand, constrained flows and historical queries across 24 hours.",
         assumptions="Original synthetic demo, INR cost label; deterministic cosine demand and daylight PV, not local measurements."),
    dict(id="campus6", title="6 buses · campus PV, battery and heat", buses=6, hours=24,
         summary="Five electrical campus locations and a heat bus: rooftop PV, tariff-driven battery operation and a heat pump.",
         expected="Battery shifts low-price imports to high-price hours; heat pump delivers 3 MW heat per MW input.",
         assumptions="Synthetic representative day; USD/MWh tariffs, COP 3, 90% charge/discharge efficiency; no AC voltage or comfort dynamics."),
    dict(id="wind10", title="10 buses · wind export bottleneck", buses=10, hours=24,
         summary="Coastal wind supplies an inland demand area through a 30 MW export corridor; local gas covers the import shortfall.",
         expected="Observe corridor saturation, wind curtailment and local generation; increasing the corridor limit is an optional experiment.",
         assumptions="Synthetic 220 kV radial corridor, explicit 24-hour wind and load shapes, fixed capacities; no weather forecasts or N-1 claim."),
    dict(id="pglib14", title="14 buses · IEEE/PGLib DC reference", buses=14, hours=1,
         summary="A licensed public benchmark subset for independently checking lossless DC dispatch and all 20 branch flows.",
         expected="259 MW demand is met by the cheaper bus-1 unit. Compare objective and port flows with a reduced-Laplacian reference.",
         assumptions="PGLib v23.07, CC BY 4.0. Lossless DC adaptation, not the published AC case. Uniform 110 kV normalization; tap effects absorbed into x. Source ratings are estimated. See bundled attribution."),
    dict(id="district14", title="14 buses · district electricity and heat", buses=14, hours=24,
         summary="A 12-bus ring, a lower-voltage district bus and a heat bus combine a transformer, PV, heat pump and battery.",
         expected="Inspect the 20 MVA transformer, COP-3 heat delivery and battery arbitrage under a three-block import tariff.",
         assumptions="Use-case variant of the existing 14-bus synthetic acceptance grid; daylight renewable renamed PV, illustrative USD offers, no measured district data."),
    dict(id="regional20", title="20 buses · regional renewable integration", buses=20, hours=24,
         summary="A meshed regional network with residential and industrial demand, northern wind, central solar, gas backup and a battery.",
         expected="Exercise larger spreadsheets, 24-hour dispatch, source-isolated flows and saved layouts; compare midday PV and evening imports.",
         assumptions="Synthetic 220 kV network, fixed offers/capacities, explicit load/wind/PV profiles and hourly weights; no utility asset inventory or expansion planning claim."),
]


def profile(project, kind, name, attribute, values, unit):
    project.profiles.append(dict(component=kind, name=name, attribute=attribute,
                                 values=list(values), unit=unit, source="Deterministic use-case demo"))


def base(name, buses, hours=24):
    project = Project(name=name, currency="USD")
    project.set_horizon("2026-01-01", hours, 60)
    for carrier in ["AC", "grid", "gas", "solar", "wind", "battery", "heat"]:
        project.upsert("Carrier", carrier, {})
    for bus in buses:
        project.upsert("Bus", bus, {"v_nom": 220, "carrier": "AC"})
    return project


def line(project, name, first, last, capacity=150):
    # Resistance is nonzero for strict consistency; the lossless solve ignores it.
    project.upsert("Line", name, dict(bus0=first, bus1=last, x=10, r=0.5, s_nom=capacity))


def generator(project, name, bus, capacity, cost, carrier):
    project.upsert("Generator", name, dict(bus=bus, p_nom=capacity, marginal_cost=cost, carrier=carrier))


def battery(project, bus, capacity):
    project.upsert("StorageUnit", "Battery", dict(bus=bus, carrier="battery", p_nom=capacity,
        max_hours=3, efficiency_store=0.9, efficiency_dispatch=0.9, cyclic_state_of_charge=True))


def congestion():
    project = base("City import congestion", ["Plant bus", "City"], 1)
    generator(project, "Remote plant", "Plant bus", 100, 20, "gas")
    generator(project, "City peaker", "City", 100, 100, "gas")
    project.upsert("Load", "City demand", dict(bus="City", p_set=60))
    line(project, "Import corridor", "Plant bus", "City", 40)
    return project


SOLAR = [max(0, math.sin((h - 6) * math.pi / 12)) for h in range(24)]
WIND = [0.80, 0.82, 0.85, 0.83, 0.78, 0.72, 0.68, 0.62, 0.58, 0.54, 0.50, 0.48,
        0.46, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.78, 0.80, 0.82, 0.84, 0.82]
DEMAND = [0.65, 0.62, 0.60, 0.60, 0.62, 0.70, 0.80, 0.90, 0.95, 0.95, 0.92, 0.90,
          0.88, 0.88, 0.90, 0.95, 1.00, 1.10, 1.15, 1.12, 1.00, 0.90, 0.80, 0.72]


def campus():
    project = base("Campus integrated energy", ["Grid", "Library", "Laboratory", "Dormitory", "Clinic", "Heat"])
    project.object("Bus", "Heat")["attributes"] = {"carrier": "heat"}
    for bus in ["Library", "Laboratory", "Dormitory", "Clinic"]:
        line(project, "Feeder " + bus, "Grid", bus, 50)
    generator(project, "Grid import", "Grid", 80, 30, "grid")
    generator(project, "Rooftop PV", "Laboratory", 30, 0, "solar")
    generator(project, "Emergency gas", "Clinic", 40, 300, "gas")
    for bus, mw in [("Library", 5), ("Laboratory", 12), ("Dormitory", 10), ("Clinic", 8)]:
        project.upsert("Load", bus + " demand", dict(bus=bus, p_set=mw))
        profile(project, "Load", bus + " demand", "p_set", [mw * d for d in DEMAND], "MW")
    project.upsert("Load", "Heat demand", dict(bus="Heat", p_set=9))
    project.upsert("Link", "Heat pump", dict(bus0="Library", bus1="Heat", p_nom=8, efficiency=3))
    battery(project, "Dormitory", 12)
    profile(project, "Generator", "Grid import", "marginal_cost", [30]*7+[70]*10+[150]*5+[30]*2, "currency/MWh")
    profile(project, "Generator", "Rooftop PV", "p_max_pu", SOLAR, "per unit")
    return project


def wind_corridor():
    names = [f"N{i:02}" for i in range(1, 11)]
    project = base("Coastal wind export corridor", names)
    for i in range(9):
        line(project, "Export bottleneck" if i == 4 else f"Corridor {i+1}", names[i], names[i+1], 30 if i == 4 else 150)
    for name, bus in [("Coastal wind A", "N01"), ("Coastal wind B", "N02")]:
        generator(project, name, bus, 60, 0, "wind")
        profile(project, "Generator", name, "p_max_pu", WIND, "per unit")
    generator(project, "Inland gas", "N10", 140, 90, "gas")
    for bus in names[6:]:
        project.upsert("Load", bus + " demand", dict(bus=bus, p_set=20))
        profile(project, "Load", bus + " demand", "p_set", [20*d for d in DEMAND], "MW")
    return project


def pglib_data():
    return json.loads((Path(__file__).parent / "data" / "pglib14_dc.json").read_text(encoding="utf-8"))


def pglib_reference():
    data = pglib_data()
    project = base("PGLib IEEE 14-bus lossless DC adaptation", [f"B{i:02}" for i in range(1, 15)], 1)
    for bus in project.objects:
        if bus["component"] == "Bus":
            bus["attributes"]["v_nom"] = 110  # Normalization only, not an asserted physical voltage.
    for i, demand in enumerate(data["load_mw"], 1):
        if demand:
            project.upsert("Load", f"Demand {i:02}", dict(bus=f"B{i:02}", p_set=demand))
    for bus, capacity, cost in data["generators_bus_pmax_cost"]:
        generator(project, f"G{bus:02}", f"B{bus:02}", capacity, cost, "gas")
    for first, last, x, tap, rating in data["branches_from_to_x_tap_rate"]:
        effective_x = x*tap*110**2/data["base_mva"]
        project.upsert("Line", f"Branch {first:02}-{last:02}", dict(bus0=f"B{first:02}", bus1=f"B{last:02}",
            x=effective_x, r=effective_x/100, s_nom=rating, v_ang_max=30))
    return project


def district():
    project = stage3_grid()
    project.name, project.currency = "District electricity and heat", "USD"
    # The acceptance grid's diurnal renewable profile represents PV here, not wind weather.
    for record in project.objects:
        if record["component"] == "Generator" and record["name"] == "Wind":
            record["name"] = "District PV"
            record["attributes"]["carrier"] = "solar"
    project.upsert("Carrier", "solar", {})
    for entry in project.profiles:
        if entry["name"] == "Wind":
            entry["name"] = "District PV"
    return project


def regional():
    names = [f"R{i:02}" for i in range(1, 21)]
    project = base("Regional renewable integration", names)
    for i in range(20):
        line(project, f"Ring {i+1:02}", names[i], names[(i+1) % 20], 120)
    for a, b in [(1, 6), (6, 11), (11, 16), (16, 1)]:
        line(project, f"Tie {a:02}-{b:02}", f"R{a:02}", f"R{b:02}", 100)
    generator(project, "Regional import", "R01", 240, 25, "grid")
    generator(project, "South gas", "R11", 180, 110, "gas")
    generator(project, "North wind", "R04", 100, 0, "wind")
    generator(project, "Central PV", "R15", 80, 0, "solar")
    profile(project, "Generator", "Regional import", "marginal_cost", [25]*7+[65]*10+[140]*5+[25]*2, "currency/MWh")
    profile(project, "Generator", "North wind", "p_max_pu", WIND, "per unit")
    profile(project, "Generator", "Central PV", "p_max_pu", SOLAR, "per unit")
    for i, bus in enumerate(names):
        mw = 12 if i % 5 == 0 else 8  # Four industrial hubs, sixteen residential districts.
        project.upsert("Load", bus + " demand", dict(bus=bus, p_set=mw))
        shape = [0.9]*6+[1.15]*12+[0.9]*6 if i % 5 == 0 else DEMAND
        profile(project, "Load", bus + " demand", "p_set", [mw*d for d in shape], "MW")
    battery(project, "R12", 30)
    return project


def illustrative_layout(project):
    """Deliberately spaced schematic ring; never interpreted as GIS coordinates."""
    graph = topology(project)
    buses = [o for o in graph["objects"] if o["kind"] == "Bus"]
    radius = max(230, 22 * len(buses))
    center = radius + 260
    positions = {}
    for i, bus in enumerate(buses):
        angle = 2*math.pi*i/len(buses)-math.pi/2
        positions[bus["key"]] = dict(x=center+radius*math.cos(angle), y=center+radius*math.sin(angle))
    counts = {}
    for obj in graph["objects"]:
        if obj["kind"] == "Bus":
            continue
        ports = [positions[k] for k in obj["buses"] if k in positions]
        if len(ports) >= 2:
            positions[obj["key"]] = dict(x=(ports[0]["x"]+ports[1]["x"])/2, y=(ports[0]["y"]+ports[1]["y"])/2)
        elif ports:
            bus = obj["buses"][0]
            n = counts.get(bus, 0)
            counts[bus] = n+1
            angle = math.atan2(ports[0]["y"]-center, ports[0]["x"]-center) + (n-0.5)*0.5
            positions[obj["key"]] = dict(x=ports[0]["x"]+145*math.cos(angle), y=ports[0]["y"]+145*math.sin(angle))
    project.schematic_layouts["current"] = dict(positions=positions, zoom=max(0.25, min(1, 480/(center*2))), panX=0, panY=0,
                                                width=max(900, center*2), height=max(520, center*2))


FACTORIES = dict(congestion2=congestion, urban3=demo_project, campus6=campus, wind10=wind_corridor,
                 pglib14=pglib_reference, district14=district, regional20=regional)


def make_demo(key):
    if key not in FACTORIES:
        raise ValueError("Choose a known demo model.")
    project = FACTORIES[key]()
    spec = next(s for s in DEMO_SPECS if s["id"] == key)
    project.demo_info = deepcopy(spec)
    project.demo_info["provenance"] = pglib_data() if key == "pglib14" else {"source": "Authored deterministic synthetic use case; no measured grid data."}
    if spec["buses"] >= 6:
        illustrative_layout(project)
    return project
