# Everyday keyboard shortcuts — RawBuild

| Shortcut (Windows) | Action |
|---|---|
| Ctrl+N | New project |
| Ctrl+O | Open native Studio SQLite project |
| Ctrl+S | Save project; first save asks for a destination |
| Ctrl+Z | Undo applied model edit, outside editable text |
| Ctrl+Y / Ctrl+Shift+Z | Redo applied model edit, outside editable text |
| F1 | Existing context-sensitive help |

New/Open/Save and model Undo use Qt standard key bindings. Redo explicitly
supports the common Windows Ctrl+Y and Ctrl+Shift+Z alternatives.
File/Data menus display the shortcuts; the quick-save tooltip includes Ctrl+S.
No additional Save As, close-project, import/export or clipboard command binding
is implied by this increment.

## Safety and focus behavior

- Keyboard commands invoke the same backend methods as menu/buttons; there is
  no shortcut-only persistence or project-replacement path.
- Ctrl+S resolves pending inspector/spreadsheet/settings/CSV drafts using existing
  prompts. Cancelling preserves the saved database and pending work.
- New/Open retain dirty-project, draft and pinned-result guards. Dialog
  cancellation does not create/replace a project.
- Commands are window-scoped, do not auto-repeat and are disabled during
  run/batch/backup work and while QML modal tools/messages are open. Native modal
  dialogs own their own keyboard focus.
- In an editable text field (including spreadsheet cell editors), Undo/Redo
  remains text editing, even if model history exists. Move focus to a non-text
  control to use model Undo/Redo, or choose the Data-menu model history command
  explicitly. The keyboard does not silently discard a text edit to undo a model.
- Ordinary text-control selection/copy/paste behavior remains unchanged; this
  feature does not introduce global clipboard shortcuts that steal field keys.

## Verification

`tests/test_keyboard_shortcuts.py` sends real Qt key events to the actual QML
window, checks saved SQLite content and exercises new/open/save, both model redo
keys, local text undo/redo, pending inspector/spreadsheet Apply/Cancel and busy/
modal suppression. Only file selection and confirmation answers are supplied
by the tests; save, replacement and history code runs normally.

Feature-only runner: `tools/validate_keyboard_shortcuts.py`. It runs native
Windows and Light/Dark shortcut checks plus related model-history/menu/draft
guards. Evidence: `docs/keyboard-shortcuts-validation/summary.json`.
The earlier missing-binding diagnosis remains in `docs/shortcut-diagnosis/`.
No full-application regression, dependency installation or release build.

Completed verification (2026-11-16): **all 40 functional tests passed** (9 native,
9 Light, 9 Dark, 13 related guards). A separate protected-folder hash guard
detected six changes in `myTest/plexos-export.xml/` during verification, so the
combined runner returns `all_passed=false` despite every test job succeeding.
This is not a shortcut failure or proof of its cause; the test projects are
temporary and do not address that path. Export-package artifacts were not
reverted or overwritten. Release/reference fingerprints remained unchanged.
