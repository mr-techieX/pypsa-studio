"""Local application identity; the SVG is the master for all icon sizes."""

from pathlib import Path
import sys


ICON_PATH = Path(__file__).resolve().parent / "assets" / "pypsa-studio.svg"


def configure_application_icon(app):
    """Apply the SVG before windows are created; do not alter user preferences."""
    from PySide6.QtGui import QIcon

    if sys.platform == "win32":
        # Keep the taskbar identity separate from the shared python.exe host.
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "LocalEnergyWorkbench.PyPSAStudio.1"
        )
    app.setDesktopFileName("pypsa-studio")
    app.setWindowIcon(QIcon(str(ICON_PATH)))
