"""Non-destructive, project-portable visibility choices for the Objects editors."""

from .schema import attribute_spec, registry


def visible_categories(project):
    chosen = project.editor_config.get("categories")
    return [name for name in registry() if chosen is None or name in chosen]


def property_specs(project, component):
    specs = list(registry()[component]["attributes"])
    known = {s["name"] for s in specs}
    for record in project.objects:
        if record["component"] == component:
            for name in record["attributes"]:
                if name not in known:
                    specs.append(attribute_spec(component, name))
                    known.add(name)
    return specs


def visible_properties(project, component):
    chosen = project.editor_config.get("properties", {}).get(component)
    return [s["name"] for s in property_specs(project, component)
            if chosen is None or s["name"] == "name" or s["name"] in chosen]


def checked_config(project, categories, properties):
    if len(set(categories)) != len(categories) or not set(categories).issubset(registry()):
        raise ValueError("Choose known component categories without duplicates.")
    clean = {}
    for component, names in properties.items():
        if component not in registry() or not isinstance(names, list):
            raise ValueError("Choose properties for a known component category.")
        if len(set(names)) != len(names):
            raise ValueError(f"{component}: duplicate property selection.")
        for name in names:
            attribute_spec(component, name)
        clean[component] = list(dict.fromkeys(["name"] + names))
    return {"categories": list(categories), "properties": clean}
