"""Bounded applied-project history, independent of disk/run/session view state."""

from copy import deepcopy
import json

from .layout_state import sheet_state


class ModelHistory:
    def __init__(self, limit=20, byte_limit=32 * 1024 * 1024):
        self.limit, self.byte_limit = limit, byte_limit
        self.undo, self.redo = [], []

    def clear(self):
        self.undo.clear()
        self.redo.clear()

    def available(self, data, redo=False):
        stack = self.redo if redo else self.undo
        return bool(stack and sheet_state(data) == sheet_state(stack[-1]["before" if redo else "after"]))

    def record(self, before, after, label, identity=None):
        # Never retain/copy multi-megabyte dialect definitions for every edit.
        # They are non-model metadata and are preserved separately during undo.
        before = {k: v for k, v in before.items() if k != "interchange_info"}
        after = {k: v for k, v in after.items() if k != "interchange_info"}
        if sheet_state(before) == sheet_state(after):
            return True  # A no-op must not destroy Redo.
        if self.undo and sheet_state(self.undo[-1]["after"]) != sheet_state(before):
            self.clear()  # Detached/external replacement cannot inherit a stale chain.
        self.redo.clear()
        size = len(json.dumps([before, after], ensure_ascii=False).encode("utf-8"))
        if size > self.byte_limit:
            self.clear()
            return False
        self.undo.append(dict(before=deepcopy(before), after=deepcopy(after), label=label,
                              identity=identity, size=size))
        while len(self.undo) > self.limit or sum(e["size"] for e in self.undo) > self.byte_limit:
            self.undo.pop(0)
        return True

    def entry(self, data, redo=False):
        if not self.available(data, redo):
            raise ValueError("Model history is empty or stale; it cannot overwrite unrelated changes.")
        return (self.redo if redo else self.undo)[-1]

    def commit_step(self, redo=False):
        source, target = (self.redo, self.undo) if redo else (self.undo, self.redo)
        target.append(source.pop())
