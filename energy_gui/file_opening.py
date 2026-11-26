"""Local file classification. Extensions route; native identity is checked on load."""

from pathlib import Path


def model_path(value):
    """Validate syntax/suffix only; safe for drag-enter without filesystem I/O."""
    from PySide6.QtCore import QUrl
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Drop one local .sqlite project or .nc results file.")
    # QUrl handles percent-escaping and literal Unicode. Never unquote OS paths.
    if value.lower().startswith("file:"):
        url = QUrl(value)
        if not url.isValid() or not url.isLocalFile() or url.host():
            raise ValueError("Network file URLs are not enabled; select a local copy.")
        if url.hasQuery() or url.hasFragment():
            raise ValueError("File URLs must escape literal #/? filename characters.")
        value = url.toLocalFile()
    if "://" in value or value.startswith(("\\\\", "//")):
        raise ValueError("Only local files are supported; remote URLs/shares are not opened.")
    path = Path(value)
    if path.suffix.lower() not in {".sqlite", ".nc"}:
        raise ValueError("Use a local .sqlite Studio project or .nc results file.")
    return path


def local_file(value):
    path = model_path(value).resolve()
    if not path.is_file():
        raise ValueError("Choose an existing model or results file, not a folder.")
    return path
