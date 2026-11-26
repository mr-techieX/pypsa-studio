"""Explicit, read-only multi-object/property queries on one frozen run's outputs."""

from pathlib import Path
import math

import pandas as pd

from .schema import registry
from .result_availability import PIECEWISE_COST_INPUT, has_nondefault_values, highs_integer_run
from .result_properties import is_result, require_results, result_spec
from .storage import load_project


class ResultsRepository:
    def __init__(self, directory, catalog, *, output_only=True):
        self.directory = Path(directory).resolve()
        self.tables = (self.directory / "tables").resolve()
        self.catalog = catalog
        self.output_only = output_only
        self._cache = {}
        self._series_indexes = {}
        if not isinstance(catalog, list) or not catalog or any(
            not isinstance(entry, dict)
            or any(not isinstance(entry.get(key), str) for key in ["component", "kind", "file", "attribute"])
            or entry["kind"] not in {"static", "time series"}
            for entry in catalog
        ):
            raise ValueError("Malformed result catalogue: expected table entries with component, kind, attribute and file. Restore a complete saved run; no artifacts were modified.")
        self.project = load_project(self.directory / "inputs.sqlite")
        self.snapshots = pd.DatetimeIndex(self.project.snapshots)
        # Scope is the run's frozen model, not PyPSA's built-in catalogues or
        # derived components, and not the currently edited project. Apply this
        # here so both the selector tree and direct queries obey the same rule.
        defined_objects = {}
        for record in self.project.objects:
            defined_objects.setdefault(record["component"], set()).add(record["name"])
        self.categories = {}
        curves = {(record["component"], record["attribute"])
                  for record in self.project.advanced_inputs.get("piecewise", [])}
        for entry in catalog:
            component = entry["component"]
            self._table_path(entry["file"])
            if component not in defined_objects:
                continue
            category = self.categories.setdefault(component, {"name": component, "objects": [], "properties": []})
            if entry["kind"] == "static":
                frame = self._read(entry["file"])
                if not len(frame.columns) or frame.columns[0] != "name" or frame.iloc[:, 0].duplicated().any():
                    raise ValueError(f"Result table {entry['file']} requires unique name identities. Restore a complete saved run; no artifacts were modified.")
                category["objects"] = [
                    name for name in frame.iloc[:, 0].astype(str)
                    if name in defined_objects[component]
                ]
                category["static_file"] = entry["file"]
                for attribute in frame.columns[1:]:
                    if output_only:
                        if not is_result(component, attribute, "static"):
                            continue
                        if self._unused_piecewise(component, attribute, curves):
                            values = frame.loc[frame["name"].isin(category["objects"]), [attribute]]
                            if not has_nondefault_values(values, 0):
                                continue
                    category["properties"].append({"name": attribute, "kind": "static", "unit": self._unit(component, attribute)})
            elif not output_only or is_result(component, entry["attribute"], "time series"):
                category.setdefault("series_files", {})[entry["attribute"]] = entry["file"]
            if (entry["kind"] == "time series" and component in {"Line", "Transformer"}
                    and entry["attribute"] == "s_max_pu"):
                category["branch_bound_series"] = entry["file"]
        # Expose each property at most once.
        for component, category in self.categories.items():
            props = {p["name"]: p for p in category["properties"]}
            series_files = category.get("series_files", {})
            for attribute, filename in list(series_files.items()):
                # Only inspect samples when frozen evidence says this field may
                # be a placeholder. Ordinary series stay lazy.
                unused_curve = self._unused_piecewise(component, attribute, curves)
                no_lp_prices = ((component, attribute) == ("Bus", "marginal_price")
                                and output_only and highs_integer_run(self.directory))
                if output_only and (unused_curve or no_lp_prices):
                    series = self._read(filename)
                    columns = [name for name in series.columns[1:] if name in defined_objects[component]]
                    if not has_nondefault_values(series[columns], 0):
                        series_files.pop(attribute)
                        continue
                props[attribute] = {"name": attribute, "kind": "time series", "unit": self._unit(component, attribute)}
            category["properties"] = sorted(props.values(), key=lambda p: p["name"])

    @staticmethod
    def _unused_piecewise(component, attribute, curves):
        return attribute in PIECEWISE_COST_INPUT and (component, PIECEWISE_COST_INPUT[attribute]) not in curves

    @staticmethod
    def _unit(component, attribute):
        spec = result_spec(component, attribute)
        if spec:
            return spec["unit"]
        definition = registry().get(component, {})
        return next((a["unit"] for a in definition.get("attributes", []) if a["name"] == attribute), "")

    def _table_path(self, filename):
        path = (self.tables / filename).resolve()
        if path.parent != self.tables or Path(filename).name != filename:
            raise ValueError("Unsafe result catalogue filename.")
        return path

    def _read(self, filename):
        path = self._table_path(filename)
        if filename not in self._cache:
            try:
                frame = pd.read_csv(path, keep_default_na=False, dtype={"name": str})
                if list(frame.columns[:2]) == ["period", "snapshot"]:
                    expected = dict(zip(self.project.snapshots, self.project.advanced_inputs.get("snapshot_periods", [])))
                    times = pd.to_datetime(frame["snapshot"]).map(lambda t: t.isoformat())
                    if times.duplicated().any() or any(expected.get(t) != p for t, p in zip(times, frame["period"])):
                        raise ValueError("Period/snapshot result identities do not match frozen inputs.")
                    frame = frame.drop(columns="period")
                self._cache[filename] = frame
            except (pd.errors.ParserError, pd.errors.EmptyDataError, UnicodeError) as error:
                raise ValueError(f"Result table {filename} is unreadable/incomplete CSV. Restore a complete saved run; no artifacts were modified.") from error
        return self._cache[filename]

    def describe(self):
        return [
            {"name": name, "objects": c["objects"], "properties": c["properties"]}
            for name, c in (sorted(self.categories.items()) if self.output_only else self.categories.items())
            if c["objects"] and c["properties"]
        ]

    def _scalar_fallback(self, component, attribute):
        return not self.output_only

    def _query_specs_for(self, component, objects, specs):
        return specs

    def series_index(self, filename):
        if filename not in self._series_indexes:
            frame = self._read(filename)
            index = pd.DatetimeIndex(pd.to_datetime(frame.iloc[:, 0]))
            if index.has_duplicates or index.hasnans or index.tz is not None:
                raise ValueError(f"Invalid result snapshot identities in {filename}.")
            self._series_indexes[filename] = index
        return self._series_indexes[filename]

    def branch_bound_inputs(self, component, attribute, snapshot):
        """Private overlay context; not exposed as queryable properties."""
        if component not in {"Line", "Transformer"} or attribute not in {"s_nom", "s_max_pu"}:
            raise ValueError("Unsupported passive branch limit context.")
        category = self.categories.get(component, {})
        names = category.get("objects", [])
        if not names or "static_file" not in category:
            return {}
        static = self._read(category["static_file"])
        values = dict(zip(static.iloc[:, 0].astype(str), static[attribute])) if attribute in static else {}
        series_file = category.get("branch_bound_series") if attribute == "s_max_pu" else None
        if series_file:
            series = self._read(series_file)
            rows = self.series_index(series_file) == pd.Timestamp(snapshot)
            for name in series.columns[1:]:
                values[name] = series.loc[rows, name].iloc[0] if rows.sum() == 1 else None
        return {name: values[name] for name in names if name in values}

    def query(self, component, objects, properties, start="", end="", aggregation=None):
        if self.output_only:
            require_results(component, properties)
        if aggregation is not None:
            from .temporal import aggregate, options
            settings = options(aggregation)
            frame, specs, temporal = self.query(component, objects, properties, start, end)
            if settings["resolution"] == "native":
                return frame, specs, temporal
            frame, specs = aggregate(self.project, component, frame, specs, settings)
            return frame, specs, True
        category = self.categories.get(component)
        if not category or not objects or not properties:
            raise ValueError("Select one object category, at least one object and one property.")
        if len(set(objects)) != len(objects) or len(set(properties)) != len(properties):
            raise ValueError("Duplicate objects or properties in query.")
        if not set(objects).issubset(category["objects"]):
            raise ValueError("Select only objects explicitly defined in this run's inputs and available in its results.")
        specs = {p["name"]: p for p in category["properties"]}
        unavailable = [attribute for attribute in properties if attribute not in specs]
        if unavailable:
            raise ValueError(f"{component}: these outputs are unavailable in this source: "
                             f"{', '.join(unavailable)}. Select available outputs and query again.")
        first = pd.Timestamp(start) if start else self.snapshots[0]
        last = pd.Timestamp(end) if end else self.snapshots[-1]
        if pd.isna(first) or pd.isna(last) or first.tzinfo is not None or last.tzinfo is not None or first > last:
            raise ValueError("Use a valid timezone-naive snapshot range with From ≤ To.")
        snapshots = self.snapshots[(self.snapshots >= first) & (self.snapshots <= last)]
        temporal = any(specs[p]["kind"] == "time series" for p in properties)
        static = self._read(category["static_file"]).copy()
        static.index = static.iloc[:, 0].astype(str)
        if temporal:
            index = pd.MultiIndex.from_product([snapshots, objects], names=["snapshot", "object"])
        else:
            index = pd.Index(objects, name="object")
        result = pd.DataFrame(index=index)
        for attribute in properties:
            if specs[attribute]["kind"] == "time series":
                filename = category["series_files"][attribute]
                series = self._read(filename)
                series_index = self.series_index(filename)
                values = pd.DataFrame(index=snapshots, columns=objects, dtype=float)
                for name in objects:
                    if name in series.columns[1:]:
                        values[name] = pd.to_numeric(series[name].set_axis(series_index).reindex(snapshots), errors="coerce")
                    elif attribute in static.columns and self._scalar_fallback(component, attribute):
                        # PyPSA varying input falls back to its scalar for other objects.
                        values[name] = static.at[name, attribute]
                result[attribute] = values.to_numpy().reshape(-1)
            else:
                by_object = static[attribute].reindex(objects)
                result[attribute] = (
                    result.index.get_level_values("object").map(by_object)
                    if temporal else by_object
                )
        result = result.reset_index()
        periods = self.project.advanced_inputs.get("snapshot_periods", [])
        if temporal and periods:
            mapping = dict(zip(self.snapshots, periods))
            result.insert(0, "period", result["snapshot"].map(mapping))
        return result, self._query_specs_for(component, objects, [specs[p] for p in properties]), temporal


def query_charts(frame, properties, temporal, chart_types=None, viewport=None):
    """One chart per numeric property: never mix MW and currency on one axis."""
    charts = []

    def point(value):
        return float(value) if pd.notna(value) and math.isfinite(float(value)) else None

    for spec in properties:
        attribute = spec["name"]
        is_temporal = temporal and spec.get("kind") != "static"
        if frame.empty or not pd.api.types.is_numeric_dtype(frame[attribute]):
            continue
        if is_temporal:
            wide = frame.pivot(index="snapshot", columns="object", values=attribute).iloc[:, :6]
            if viewport is not None:
                first, last = viewport
                wide = wide.iloc[first:last+1]
            selected_count = len(wide)
            if selected_count > 1000:
                positions = [i*(selected_count-1)//999 for i in range(1000)]
                sampled = wide.iloc[positions].copy()
                # Do not bridge missing regions hidden between sampled points.
                for col in wide:
                    missing = wide[col].isna().to_numpy()
                    for i in range(1, len(positions)):
                        if missing[positions[i-1]:positions[i]+1].any():
                            sampled.iloc[i, sampled.columns.get_loc(col)] = float("nan")
                wide = sampled
            labels = wide.index.astype(str).tolist()
            if "period" in frame:
                periods = frame.drop_duplicates("snapshot").set_index("snapshot")["period"]
                labels = [f"{periods.loc[t]} · {label}" for t,label in zip(wide.index,labels)]
            series = [{"name": str(name), "values": [point(v) for v in wide[name]]} for name in wide]
        else:
            scalar = frame.drop_duplicates("object")
            labels = scalar["object"].astype(str).tolist()[:1000]
            series = [{"name": attribute, "values": [point(v) for v in scalar[attribute].iloc[:1000]]}]
        options = ["line", "bar", "dot"] if is_temporal else ["bar", "horizontal bar", "dot"]
        values = pd.to_numeric(frame[attribute], errors="coerce")
        if is_temporal and spec["unit"] in {"MW", "MWh"} and values.map(math.isfinite).all() and (values >= -1e-8).all():
            options.append("stacked area")
        kind = (chart_types or {}).get(attribute, "line" if is_temporal else "bar")
        if kind not in options:
            raise ValueError(f"{attribute}: {kind} is incompatible with these data/units. Choose {', '.join(options)}.")
        hint = (
            "Time series: line, bar or dot. Stacked area requires complete, nonnegative MW/MWh data."
            if is_temporal else
            "Static object comparison: bar, horizontal bar or dot. Line/area require time-series data."
        )
        if is_temporal:
            hint += f" Visible range: {selected_count} snapshots; {len(labels)} plotted (≤1000; evenly sampled when larger, not an extrema envelope)."
        if "metric" in spec:
            hint += f" Metric: {spec['metric']}; {spec['weighting']}. Calendar buckets may be partial; see table coverage."
        # Keep tall horizontal canvases below texture-size limits. This is a
        # preview only; the table/CSV and the captured query stay unchanged.
        if kind == "horizontal bar":
            labels = labels[:100]
            series = [{**s, "values": s["values"][:100]} for s in series]
            hint += " Horizontal-bar preview: first 100 objects; CSV includes all queried rows."
        charts.append({"title": attribute, "unit": spec["unit"], "kind": kind, "options": options,
                       "hint": hint, "labels": labels, "series": series})
    return charts
