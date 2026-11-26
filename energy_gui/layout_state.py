"""View and interchange metadata are not model/history compatibility inputs."""

def sheet_state(data):
    return {key: value for key, value in data.items() if key not in {
        "schematic_layouts", "analysis_workspace", "scenario_library", "interchange_info",
    }}
