"""Staged static-input spreadsheet; no live project mutation before Apply."""

from copy import deepcopy
import csv
import io

from .project import Project
from .schema import attribute_spec, parse_value, registry
from .editor_config import visible_properties
from .layout_state import sheet_state

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Property, Qt, Signal, Slot


def cell_text(value):
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)


class ObjectSheet(QAbstractTableModel):
    statusChanged = Signal()
    TEXT, HINT, LOCKED = range(Qt.ItemDataRole.UserRole + 1, Qt.ItemDataRole.UserRole + 4)

    def __init__(self, can_edit, parent=None):
        super().__init__(parent)
        self.can_edit = can_edit
        self.component = "Bus"
        self.baseline = None
        self.columns = ["name"]
        self.rows = []
        self.clean_rows = []
        self.original_names = []
        self.report = ""
        self.allowed_columns = None

    @Property(bool, notify=statusChanged)
    def dirty(self):
        return self.rows != self.clean_rows

    @Property(str, notify=statusChanged)
    def validationReport(self):
        return self.report

    @Property("QVariantList", notify=statusChanged)
    def availableColumns(self):
        return [a["name"] for a in registry()[self.component]["attributes"]
                if a["input"] and a["static"] and a["name"] not in self.columns
                and (self.allowed_columns is None or a["name"] in self.allowed_columns)]

    def roleNames(self):
        return {Qt.ItemDataRole.DisplayRole: b"display", self.TEXT: b"cellText", self.HINT: b"cellHint", self.LOCKED: b"locked"}

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.columns)

    @Slot(int, result=str)
    def columnName(self, column):
        return self.columns[column] if 0 <= column < len(self.columns) else ""

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row, column = index.row(), index.column()
        if role in (self.TEXT, Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return self.rows[row][column]
        if role == self.LOCKED:
            return column == 0 and self.original_names[row] is not None
        if role == self.HINT:
            return self.column_hint(column)
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole:
            if orientation == Qt.Orientation.Vertical:
                return str(section+1)
            name = self.columns[section]
            unit = attribute_spec(self.component, name)["unit"]
            return name + (f" [{unit}]" if unit else "")
        return None

    def column_hint(self, column):
        name = self.columns[column]
        if name == "name":
            return "Unique object name. Existing names are locked; renaming is not part of this editor yet."
        spec = attribute_spec(self.component, name)
        return f"{spec['description']}\nUnit: {spec['unit'] or 'none'} · default: {spec['default']}\nBlank removes this explicit input; PyPSA uses its default."

    def flags(self, index):
        result = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.isValid() and not self.data(index, self.LOCKED):
            result |= Qt.ItemFlag.ItemIsEditable
        return result

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if not self.can_edit() or not index.isValid() or role != Qt.ItemDataRole.EditRole:
            return False
        if self.data(index, self.LOCKED):
            return False
        value = str(value)
        if self.rows[index.row()][index.column()] != value:
            self.rows[index.row()][index.column()] = value
            self.report = "Draft changed — validate or Apply. The project is unchanged."
            self.dataChanged.emit(index, index, [self.TEXT])
            self.statusChanged.emit()
        return True

    @Slot(int, int, str, result=bool)
    def editCell(self, row, column, value):
        if not (0 <= row < len(self.rows) and 0 <= column < len(self.columns)):
            return False
        return self.setData(self.index(row, column), value)

    def load(self, project, component):
        self.beginResetModel()
        self.component = component
        self.baseline = deepcopy(project.model_state())
        configured = project.editor_config.get("properties", {}).get(component)
        self.allowed_columns = set(visible_properties(project, component)) if configured is not None else None
        records = [o for o in project.objects if o["component"] == component]
        # Configuration defines which fields may be edited, not which empty
        # default columns to open. Only explicitly stored properties form the
        # initial grid; omitted values remain PyPSA defaults, never materialised.
        explicit = list(dict.fromkeys(n for o in records for n in o["attributes"]))
        self.columns = ["name"] + [
            name for name in explicit
            if name != "name"
            and attribute_spec(component, name)["input"]
            and attribute_spec(component, name)["static"]
            and (self.allowed_columns is None or name in self.allowed_columns)
        ]
        self.rows = [[o["name"]] + [cell_text(o["attributes"][n]) if n in o["attributes"] else "" for n in self.columns[1:]] for o in records]
        self.clean_rows = deepcopy(self.rows)
        self.original_names = [o["name"] for o in records]
        self.report = "Blank cells use PyPSA defaults. Apply changes the project; Save writes SQLite."
        self.endResetModel()
        self.statusChanged.emit()

    def _check_column(self, name):
        spec = attribute_spec(self.component, name)
        if self.allowed_columns is not None and name not in self.allowed_columns:
            raise ValueError(f"{name} is hidden. Enable it in Configuration before editing or pasting it.")
        if not registry()[self.component]["editable"] or not spec["input"] or not spec["static"]:
            raise ValueError(f"{name}: only editable static inputs are accepted.")

    @Slot(str, result=bool)
    def addColumn(self, name):
        try:
            if not self.can_edit():
                return False
            self._check_column(name)
            if name in self.columns:
                return True
            self.beginResetModel()
            self.columns.append(name)
            by_name = {o["name"]: o["attributes"] for o in self.baseline["objects"] if o["component"] == self.component}
            for i, row in enumerate(self.rows):
                attrs = by_name.get(self.original_names[i], {})
                row.append(cell_text(attrs[name]) if name in attrs else "")
            for i, row in enumerate(self.clean_rows):
                attrs = by_name.get(self.original_names[i], {})
                row.append(cell_text(attrs[name]) if name in attrs else "")
            self.endResetModel()
            self.report = f"Added column {name}. No model data changes until Apply."
            self.statusChanged.emit()
            return True
        except ValueError as error:
            self.report = str(error)
            self.statusChanged.emit()
            return False

    @Slot(result=bool)
    def addRow(self):
        if not self.can_edit() or not registry()[self.component]["editable"] or len(self.rows) >= 10000:
            return False
        self.beginInsertRows(QModelIndex(), len(self.rows), len(self.rows))
        self.rows.append([""] * len(self.columns))
        self.original_names.append(None)
        self.endInsertRows()
        self.report = f"Added row {len(self.rows)}. Enter its name and required inputs, then Apply."
        self.statusChanged.emit()
        return True

    @Slot(result=str)
    def copyTsv(self):
        output = io.StringIO(newline="")
        writer = csv.writer(output, delimiter="\t", lineterminator="\n")
        writer.writerow(self.columns)
        writer.writerows(self.rows)
        return output.getvalue()

    @Slot(str, result=bool)
    def pasteTsv(self, text):
        try:
            if not self.can_edit() or not registry()[self.component]["editable"]:
                return False
            if len(text.encode("utf-8")) > 2_000_000:
                raise ValueError("Paste is limited to 2 MB / 10000 objects per batch.")
            table = list(csv.reader(io.StringIO(text), delimiter="\t", strict=True))
            if len(table) < 2 or len(table) > 10001:
                raise ValueError("Paste a TSV table with a header row and 1–10000 object rows.")
            headers = [n.strip() for n in table[0]]
            if "name" not in headers or len(set(headers)) != len(headers):
                raise ValueError("Headers must be unique attribute names and include name.")
            for name in headers:
                self._check_column(name)
            name_column = headers.index("name")
            names, seen = [], set()
            for number, row in enumerate(table[1:], start=2):
                if len(row) != len(headers) or not row[name_column].strip():
                    raise ValueError(f"TSV row {number}: provide a name and exactly {len(headers)} columns.")
                name = row[name_column].strip()
                if name in seen:
                    raise ValueError(f"TSV row {number}: duplicate name '{name}'.")
                names.append(name)
                seen.add(name)
                for attribute, value in zip(headers, row):
                    if attribute != "name" and value != "":
                        try:
                            parse_value(attribute_spec(self.component, attribute), value)
                        except (ValueError, TypeError) as error:
                            raise ValueError(f"TSV row {number}, {attribute}: {error}") from error
            # Validate the complete paste before changing even the staged grid.
            existing = {row[0].strip(): i for i, row in enumerate(self.rows) if row[0].strip()}
            if len(self.rows) + sum(name not in existing for name in names) > 10000:
                raise ValueError("The spreadsheet is limited to 10000 object rows.")
            for name in headers:
                self.addColumn(name)
            self.beginResetModel()
            for name, values in zip(names, table[1:]):
                if name not in existing:
                    existing[name] = len(self.rows)
                    self.rows.append([""] * len(self.columns))
                    self.original_names.append(None)
                target = self.rows[existing[name]]
                for attribute, value in zip(headers, values):
                    target[self.columns.index(attribute)] = name if attribute == "name" else value
            self.report = f"Staged {len(names)} object rows. Validate / Apply to update the project."
            self.endResetModel()
            self.statusChanged.emit()
            return True
        except (ValueError, TypeError, csv.Error) as error:
            self.report = str(error)
            self.statusChanged.emit()
            return False

    def candidate(self, project):
        if sheet_state(self.baseline) != project.model_state():
            raise ValueError("The project changed outside this spreadsheet. Copy your draft, Discard/reload, then paste it again.")
        result = Project(**project.to_dict())
        seen = set()
        for i, row in enumerate(self.rows):
            if self.original_names[i] is None and not any(row):
                continue  # An untouched blank Add row is not a model object.
            name = row[0].strip()
            if not name or name in seen:
                raise ValueError(f"Row {i+1}, name: provide a unique object name.")
            seen.add(name)
            original = result.object(self.component, self.original_names[i])
            attrs = deepcopy(original["attributes"]) if original else {}
            for column, attribute in enumerate(self.columns[1:], start=1):
                # Unedited blank/string values must retain their original meaning.
                if i < len(self.clean_rows) and row[column] == self.clean_rows[i][column]:
                    continue
                if row[column] == "":
                    attrs.pop(attribute, None)
                else:
                    try:
                        attrs[attribute] = parse_value(attribute_spec(self.component, attribute), row[column])
                    except (ValueError, TypeError) as error:
                        raise ValueError(f"Row {i+1}, {attribute}: {error}") from error
            result.upsert(self.component, name, attrs)
        errors = result.validate()
        # Existing incomplete models may be repaired category by category. Never
        # introduce a new structural/engineering error, but don't deadlock repair
        # because an unrelated category already has an error.
        introduced = sorted(set(errors) - set(project.validate()))
        if introduced:
            raise ValueError("Apply blocked — fix these new errors:\n" + "\n".join(introduced))
        return result, errors

    def validate_changes(self, project):
        try:
            candidate, errors = self.candidate(project)
            self.report = "Draft checks passed." + (" Existing model issues:\n" + "\n".join(errors) if errors else " Full model input checks passed; solver feasibility is not yet established.")
            self.statusChanged.emit()
            return candidate
        except (ValueError, TypeError) as error:
            self.report = str(error)
            self.statusChanged.emit()
            return None
