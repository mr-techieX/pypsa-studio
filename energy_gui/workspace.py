"""Session-only query snapshots. No project files or run artifacts are changed."""

from copy import deepcopy
from dataclasses import dataclass, field
import uuid

import pandas as pd


@dataclass
class QueryTab:
    title: str
    run_path: str
    run_meta: dict
    criteria: dict
    frame: pd.DataFrame
    specs: list[dict]
    temporal: bool
    description: str
    pinned: bool = False
    chart_types: dict = field(default_factory=dict)
    view: int = 0
    listing: str = "snapshot"
    table_form: str = "wide"
    chart_range: list = field(default_factory=lambda: [0, -1])
    sort_column: str = ""
    sort_descending: bool = False
    id: str = field(default_factory=lambda: uuid.uuid4().hex)


class QueryWorkspace:
    def __init__(self):
        self.tabs = []
        self.active_id = ""

    @property
    def active(self):
        return next((tab for tab in self.tabs if tab.id == self.active_id), None)

    def put(self, **values):
        """Reuse the single unpinned preview, never mutate a pinned snapshot."""
        preview = next((tab for tab in self.tabs if not tab.pinned), None)
        values = deepcopy(values)
        values["frame"] = values["frame"].copy(deep=True)
        tab = QueryTab(**values)
        if preview:
            tab.id = preview.id
            self.tabs[self.tabs.index(preview)] = tab
        else:
            self.tabs.append(tab)
        self.active_id = tab.id
        return tab

    def select(self, tab_id):
        if not any(t.id == tab_id for t in self.tabs):
            raise ValueError("Query tab no longer exists.")
        self.active_id = tab_id
        return self.active

    def toggle_pin(self, tab_id):
        tab = next(t for t in self.tabs if t.id == tab_id)
        if tab.pinned:
            # Unpinning makes this the preview. Preserve any other preview by
            # pinning it rather than silently discarding its data.
            for other in self.tabs:
                if other is not tab and not other.pinned:
                    other.pinned = True
        tab.pinned = not tab.pinned

    def close(self, tab_id):
        index = next(i for i, tab in enumerate(self.tabs) if tab.id == tab_id)
        self.tabs.pop(index)
        if self.active_id == tab_id:
            self.active_id = self.tabs[min(index, len(self.tabs)-1)].id if self.tabs else ""

    def clear(self):
        self.tabs.clear()
        self.active_id = ""
