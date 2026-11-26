"""Read queryable PyPSA variables from a standalone NetCDF, without filling defaults."""

from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import re
from tempfile import TemporaryDirectory

import numpy as np
import pandas as pd
import xarray as xr

from .project import Project
from .results import ResultsRepository
from .result_properties import is_result, require_results
from .schema import registry
from .temporal import available_resolutions


MAX_FILE_BYTES = 512 * 1024**2
MAX_CELLS = 8_000_000
MAX_SNAPSHOTS = 100_000
MAX_VARIABLES = 2048
MAX_OBJECTS = 25_000
MAX_QUERY_CELLS = 2_000_000
MAX_TEXT_CHARS = 8_000_000
WEIGHTS = ("objective", "stores", "generators")
RESERVED = {"object", "snapshot", "period", "bucket_end", "coverage_hours", "bucket_hours",
            "partial", "property", "value", "kind", "row_kind"}


def context_attribute(attribute):
    return attribute in {"carrier", "unit", "bus"} or re.fullmatch(r"bus\d+", attribute) is not None


def identities(values):
    if any(not isinstance(value, str) or not value or len(value) > 1024 for value in values):
        raise ValueError("Invalid PyPSA NetCDF object identities.")
    if len(set(values)) != len(values):
        raise ValueError("Duplicate PyPSA NetCDF object identities.")
    return list(values)


def check_cancelled(cancelled):
    if cancelled():
        raise ValueError("Opening NetCDF was cancelled.")


@contextmanager
def archive_path(path, cancelled):
    if os.name != "nt" or str(path).isascii():
        yield path
        return
    # The current Windows netCDF4 library can interpret UTF-8 filenames with
    # the ANSI code page. Copy to a private short-lived ASCII filename rather
    # than opening a differently named sibling or changing the original.
    with TemporaryDirectory(prefix="studio-netcdf-") as directory:
        if not directory.isascii():
            raise ValueError("NetCDF cannot open this Unicode path with the current Windows temporary directory. "
                             "Copy the archive to a local path containing only ASCII characters and retry.")
        staged = Path(directory) / "archive.nc"
        size = 0
        with path.open("rb") as source, staged.open("wb") as target:
            while chunk := source.read(1024**2):
                check_cancelled(cancelled)
                size += len(chunk)
                if size > MAX_FILE_BYTES:
                    raise ValueError("NetCDF file exceeds the 512 MiB viewer limit.")
                target.write(chunk)
        yield staged


class NetcdfResults(ResultsRepository):
    """In-memory, bounded tables read directly from PyPSA's serialized variables."""

    def __init__(self, path, cancelled=lambda: False):
        self.path = Path(path).resolve()
        self._cache, self._series_indexes, self.categories = {}, {}, {}
        self.output_only = True
        self.has_weights = False
        self._text_chars = 0
        if self.path.stat().st_size > MAX_FILE_BYTES:
            raise ValueError("NetCDF file exceeds the 512 MiB viewer limit.")
        with self.path.open("rb") as stream:
            magic = stream.read(8)
        if not (magic.startswith((b"CDF\x01", b"CDF\x02", b"CDF\x05")) or magic == b"\x89HDF\r\n\x1a\n"):
            raise ValueError("Not a supported NetCDF file.")
        check_cancelled(cancelled)
        with archive_path(self.path, cancelled) as readable, xr.open_dataset(readable, engine="netcdf4", decode_cf=False,
                             cache=False, create_default_indexes=False) as raw:
            version = raw.attrs.get("network_pypsa_version")
            if not isinstance(version, str) or not version.strip():
                raise ValueError("NetCDF is not a PyPSA network archive.")
            if (len(raw.variables) > MAX_VARIABLES or sum(v.size for v in raw.variables.values()) > MAX_CELLS
                    or not 1 <= raw.sizes.get("snapshots", 0) <= MAX_SNAPSHOTS):
                raise ValueError("NetCDF exceeds the viewer's variable, snapshot or decoded cell limit.")
            # Select only the viewer's flat variables before CF decoding. In
            # particular, don't build indexes or decode dates for unknown fields.
            axes = {"snapshots_snapshot", "snapshots_timestep", "snapshots_period",
                    *(f"snapshots_{name}" for name in WEIGHTS)}
            axis_names = {"snapshots_snapshot", "snapshots_timestep"}
            keep = {name for name in axes if name in raw.variables and raw[name].dims == ("snapshots",)}
            groups = {}
            object_count = 0
            for kind, definition in registry().items():
                check_cancelled(cancelled)
                prefix = definition["list_name"]
                dim = f"{prefix}_i"
                if dim not in raw.variables or not raw.sizes.get(dim):
                    continue
                object_count += raw.sizes[dim]
                if object_count > MAX_OBJECTS:
                    raise ValueError("NetCDF exceeds the viewer's component object limit.")
                keep.add(dim)
                entries = groups[kind] = []
                for key, variable in raw.variables.items():
                    if not key.startswith(prefix + "_") or key == dim:
                        continue
                    attr = key[len(prefix) + 1:]
                    if variable.dims == (dim,) or (variable.dims[:1] == (dim,) and variable.dtype.kind == "S"):
                        temporal = False
                    elif (attr.startswith("t_") and variable.dims == ("snapshots", key + "_i")
                          and key + "_i" in raw.variables
                          and raw.sizes[key + "_i"] <= raw.sizes[dim]):
                        attr, temporal = attr[2:], True
                    else:
                        continue
                    if not attr or attr in RESERVED:
                        continue
                    kind_name = "time series" if temporal else "static"
                    if not is_result(kind, attr, kind_name) and (temporal or not context_attribute(attr)):
                        continue
                    entries.append((key, attr, temporal))
                    keep.add(key)
                    if temporal:
                        keep.add(key + "_i")
            data = xr.decode_cf(raw, drop_variables=set(raw.variables) - keep,
                                decode_times={name: name in axis_names for name in keep},
                                decode_timedelta=False, decode_coords=False)
            self._load(data, groups, cancelled)

    def _read(self, filename):
        return self._cache[filename]

    def _load(self, data, groups, cancelled):
        def check():
            check_cancelled(cancelled)

        variables = data.variables
        check()
        axis = variables.get("snapshots_timestep", variables.get("snapshots_snapshot"))
        if axis is None or axis.dims != ("snapshots",) or axis.dtype.kind != "M":
            raise ValueError("This viewer requires PyPSA datetime snapshots.")
        self.snapshots = pd.DatetimeIndex(axis.values)
        if self.snapshots.hasnans or self.snapshots.has_duplicates or not self.snapshots.is_monotonic_increasing:
            raise ValueError("NetCDF snapshots must be unique, valid, and sorted.")
        advanced = {}
        periods = variables.get("snapshots_period")
        if periods is not None:
            if periods.dims != ("snapshots",) or periods.dtype.kind not in "iu":
                raise ValueError("Invalid NetCDF period identities.")
            advanced["snapshot_periods"] = periods.values.tolist()
            advanced["periods"] = list(dict.fromkeys(advanced["snapshot_periods"]))
        columns = [variables.get(f"snapshots_{name}") for name in WEIGHTS]
        if all(v is not None and v.dims == ("snapshots",) and v.dtype.kind in "ifu" for v in columns):
            values = np.column_stack([v.values for v in columns])
            if np.isfinite(values).all() and (values > 0).all():
                advanced["weights"] = pd.DataFrame(values, columns=WEIGHTS).to_dict("records")
                self.has_weights = True
        objects = []
        for kind, entries in groups.items():
            check()
            definition = registry()[kind]
            prefix = definition["list_name"]
            dim = f"{prefix}_i"
            names = identities(self._values(variables[dim]))
            static, series, props = {}, {}, {}
            for key, attr, temporal in entries:
                check()
                variable = variables[key]
                if not temporal and variable.dims == (dim,) and variable.dtype.kind in "biufOUS":
                    if is_result(kind, attr, "static"):
                        static[attr] = self._values(variable)
                        props.setdefault(attr, dict(name=attr, kind="static", unit=self._unit(kind, attr)))
                    elif context_attribute(attr):
                        static[attr] = self._values(variable)
                elif temporal and variable.dtype.kind in "biuf" and is_result(kind, attr, "time series"):
                    columns = identities(self._values(variables[key + "_i"]))
                    if not set(columns) <= set(names):
                        raise ValueError(f"{key}: unknown object identity.")
                    frame = pd.DataFrame(self._values(variable), columns=columns)
                    frame.insert(0, self._identity_column(columns), self.snapshots)
                    self._cache[key] = frame
                    series[attr] = key
                    props[attr] = dict(name=attr, kind="time series", unit=self._unit(kind, attr))
            # Calendar grouping needs only explicit carrier and bus/unit metadata.
            context = {k: v for k, v in static.items() if context_attribute(k)}
            objects.extend(dict(component=kind, name=name, attributes={k: v[i] for k, v in context.items()})
                           for i, name in enumerate(names))
            if props:
                frame = pd.DataFrame(static, index=names)
                frame.insert(0, self._identity_column(static), names)
                self._cache[dim] = frame
                self.categories[kind] = dict(objects=names, properties=sorted(props.values(), key=lambda p: p["name"]),
                                             static_file=dim, series_files=series)
        meta = data.attrs.get("meta")
        provenance = {}
        if isinstance(meta, str) and len(meta) <= 256_000:
            try:
                provenance = json.loads(meta).get("studio_replay", {})
            except (ValueError, AttributeError):
                pass
        replay = isinstance(provenance, dict) and provenance.get("kind") == "sequential_replay"
        self.description = ("Sequential replay · not a full-horizon optimum"
                            if replay else "Standalone PyPSA archive · solve status unverified")
        if not self.categories:
            self.description += " · no queryable outputs stored"
        self.meta = {"source_kind": "netcdf", "status": self.description}
        objective = data.attrs.get("network__objective")
        if isinstance(objective, (float, int, np.number)) and math.isfinite(objective):
            self.meta["objective"] = float(objective)
            label = "Summed step objective" if replay else "Reported objective"
            self.description += f" · {label}: {objective:.12g}"
        self.project = Project(snapshots=[t.isoformat() for t in self.snapshots],
                               advanced_inputs=advanced, objects=objects)
        self._object_attrs = {(row["component"], row["name"]): row["attributes"] for row in objects}
        self.snapshot_labels = self.project.snapshots
        self._calendar_resolutions = available_resolutions(self.project) if self.has_weights else ["native"]
        check()

    @staticmethod
    def _identity_column(existing):
        key = "snapshot"
        while key in existing:
            key = "_" + key
        return key

    def _values(self, variable):
        values = variable.values
        if values.dtype.kind in "OUS":
            for value in values.flat:
                if not isinstance(value, str) or len(value) > 4096:
                    raise ValueError("Unsupported NetCDF text data.")
                self._text_chars += len(value)
                if self._text_chars > MAX_TEXT_CHARS:
                    raise ValueError("NetCDF exceeds the viewer's decoded text limit.")
        return values

    def _query_specs_for(self, component, objects, specs):
        result = []
        for spec in specs:
            unit = spec["unit"]
            if unit in {"MW", "MWh", "MVA", "MVAr"}:
                port = re.fullmatch(r"[pq](\d+)", spec["name"])
                units = set()
                for name in objects:
                    attrs = self._object_attrs[component, name]
                    terminal = f"bus{port[1]}" if port else ("bus" if "bus" in attrs else "bus0")
                    bus = attrs if component == "Bus" else self._object_attrs.get(("Bus", attrs.get(terminal, "")))
                    # PyPSA defines MW as the implied unit of a saved Bus
                    # without an explicit unit. Don't assume it for a missing bus.
                    declared = attrs.get("unit") or (bus.get("unit") or "MW" if bus is not None else "")
                    units.add(unit if declared == "MW" else declared if unit == "MW" else "")
                unit = next(iter(units)) if len(units) == 1 else ""
            result.append({**spec, "unit": unit})
        return result

    def query(self, component, objects, properties, start="", end="", aggregation=None):
        require_results(component, properties)
        first = pd.Timestamp(start) if start else self.snapshots[0]
        last = pd.Timestamp(end) if end else self.snapshots[-1]
        if first.tzinfo is None and last.tzinfo is None:
            props = self.categories.get(component, {}).get("properties", [])
            temporal = any(p["name"] in properties and p["kind"] == "time series" for p in props)
            count = max(1, self.snapshots.searchsorted(last, side="right") - self.snapshots.searchsorted(first)) if temporal else 1
            if count * len(objects) * len(properties) > MAX_QUERY_CELLS:
                raise ValueError("NetCDF query is too large. Select fewer objects/properties or a shorter date range.")
        if aggregation and aggregation.get("resolution", "native") != "native" and not self.has_weights:
            raise ValueError("Calendar aggregation requires explicit valid NetCDF snapshot weights.")
        return super().query(component, objects, properties, start, end, aggregation)
