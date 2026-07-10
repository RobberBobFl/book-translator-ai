"""Application theming: light/dark styles and system theme auto-detection.

The active theme is stored in the app config under the ``theme`` key and can
take one of three values:

* ``"auto"``  — follow the operating system / desktop environment setting
* ``"light"`` — always light
* ``"dark"``  — always dark
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from PyQt6.QtWidgets import QApplication

# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

THEME_AUTO = "auto"
THEME_LIGHT = "light"
THEME_DARK = "dark"

_LABELS: dict[str, str] = {
    THEME_AUTO: "🌗 Авто",
    THEME_LIGHT: "☀️ Светлая",
    THEME_DARK: "🌙 Тёмная",
}

# Map a combo-box label back to a theme key.
_LABEL_TO_THEME: dict[str, str] = {v: k for k, v in _LABELS.items()}

# Path to the dropdown-arrow image used by the dark stylesheet.
ARROW_PATH = Path(__file__).parent / "assets" / "combobox_arrow.png"


def theme_label(theme: str) -> str:
    """Return the human-readable label for *theme* (falls back to Auto)."""
    return _LABELS.get(theme, _LABELS[THEME_AUTO])


def label_to_theme(label: str) -> str:
    """Return the theme key for a combo-box *label* (falls back to Auto)."""
    return _LABEL_TO_THEME.get(label, THEME_AUTO)


# ---------------------------------------------------------------------------
# System theme detection
# ---------------------------------------------------------------------------


def detect_system_theme() -> str:
    """Detect whether the desktop environment uses a dark or light theme.

    Returns ``"dark"`` or ``"light"``. Detection order:

    1. ``GTK_THEME`` environment variable (``...:dark``)
    2. XDG desktop portal ``color-scheme`` (``gdbus``)
    3. KDE ``~/.config/kdeglobals`` (view background luminance / scheme name)
    4. GNOME ``gsettings`` (``color-scheme`` / ``gtk-theme``)

    Any failure is swallowed and we fall back to ``"light"``.
    """
    try:
        gtk_theme = os.environ.get("GTK_THEME", "")
        if gtk_theme:
            lowered = gtk_theme.lower()
            if "dark" in lowered:
                return THEME_DARK
            if "light" in lowered:
                return THEME_LIGHT

        portal = _detect_portal()
        if portal is not None:
            return portal

        kde = _detect_kde()
        if kde is not None:
            return kde

        gnome = _detect_gnome()
        if gnome is not None:
            return gnome
    except Exception:
        # Never let theme detection crash the app startup.
        pass

    return THEME_LIGHT


def _detect_portal() -> str | None:
    """Read the XDG settings portal ``color-scheme`` value via ``gdbus``."""
    try:
        out = subprocess.run(
            [
                "gdbus", "call", "--session",
                "--dest", "org.freedesktop.portal.Desktop",
                "--object-path", "/org/freedesktop/portal/desktop",
                "--method", "org.freedesktop.portal.Settings.Read",
                "org.freedesktop.appearance", "color-scheme",
            ],
            capture_output=True, text=True, timeout=2,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None

    m = re.search(r"(\d+)", out)
    if not m:
        return None
    code = int(m.group(1))
    # 0 = no preference, 1 = light, 2 = dark
    if code == 2:
        return THEME_DARK
    if code == 1:
        return THEME_LIGHT
    return None


def _detect_kde() -> str | None:
    """Detect KDE Plasma dark mode from ``~/.config/kdeglobals``.

    Uses the ``[Colors:View] BackgroundNormal`` RGB value (most reliable) and
    falls back to the colour-scheme name when that is unavailable.
    """
    path = Path.home() / ".config" / "kdeglobals"
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None

    section: str | None = None
    bg: str | None = None
    scheme_name: str | None = None

    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            continue
        if section == "Colors:View" and line.lower().startswith("backgroundnormal"):
            bg = line.split("=", 1)[1].strip()
        elif section == "General" and line.lower().startswith("colorscheme"):
            scheme_name = line.split("=", 1)[1].strip().lower()

    if bg:
        parts = bg.split(",")
        if len(parts) >= 3:
            try:
                r, g, b = (int(float(p)) for p in parts[:3])
                # Relative luminance (0..1); < 0.5 is dark.
                luminance = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0
                return THEME_DARK if luminance < 0.5 else THEME_LIGHT
            except ValueError:
                pass

    if scheme_name is not None:
        return THEME_DARK if "dark" in scheme_name else THEME_LIGHT

    return None


def _detect_gnome() -> str | None:
    """Detect GNOME dark mode via ``gsettings``."""
    try:
        out = subprocess.run(
            ["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
            capture_output=True, text=True, timeout=2,
        ).stdout.strip().lower()
        if "dark" in out:
            return THEME_DARK
        if "light" in out:
            return THEME_LIGHT
    except (OSError, subprocess.SubprocessError):
        pass

    try:
        out = subprocess.run(
            ["gsettings", "get", "org.gnome.desktop.interface", "gtk-theme"],
            capture_output=True, text=True, timeout=2,
        ).stdout.strip().lower()
        if "dark" in out:
            return THEME_DARK
        if "light" in out:
            return THEME_LIGHT
    except (OSError, subprocess.SubprocessError):
        pass

    return None


# ---------------------------------------------------------------------------
# Theme resolution & application
# ---------------------------------------------------------------------------


def resolve_theme(theme: str) -> str:
    """Return a concrete theme (``"dark"`` / ``"light"``) for *theme*.

    ``"auto"`` is resolved through :func:`detect_system_theme`.
    """
    if theme == THEME_AUTO:
        return detect_system_theme()
    return theme


def _dark_qss() -> str:
    """Return the dark stylesheet with the arrow asset path substituted."""
    return DARK_QSS.replace("__ARROW_PATH__", str(ARROW_PATH).replace("\\", "/"))


def apply_theme(theme: str) -> None:
    """Apply *theme* (``auto``/``light``/``dark``) to the running application."""
    app = QApplication.instance()
    if app is None:
        return
    app.setStyleSheet(_dark_qss() if resolve_theme(theme) == THEME_DARK else "")


# ---------------------------------------------------------------------------
# Dark stylesheet
# ---------------------------------------------------------------------------

DARK_QSS = """
QWidget {
    background-color: #25282f;
    color: #e6e6e6;
    font-size: 13px;
}
QMainWindow, QDialog {
    background-color: #25282f;
}
QMenuBar {
    background-color: #1f2127;
    color: #e6e6e6;
}
QMenuBar::item:selected {
    background-color: #3a3f4b;
}
QMenu {
    background-color: #2b2e36;
    color: #e6e6e6;
    border: 1px solid #3a3f4b;
}
QMenu::item:selected {
    background-color: #4f8cff;
    color: #ffffff;
}
QStatusBar {
    background-color: #1f2127;
    color: #b9bdc7;
}
QTabWidget::pane {
    border: 1px solid #3a3f4b;
    background-color: #25282f;
}
QTabBar::tab {
    background-color: #2b2e36;
    color: #b9bdc7;
    padding: 8px 16px;
    border: 1px solid #3a3f4b;
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
}
QTabBar::tab:selected {
    background-color: #25282f;
    color: #ffffff;
    border-bottom: 2px solid #4f8cff;
}
QTabBar::tab:hover {
    background-color: #353a45;
}
QGroupBox {
    border: 1px solid #3a3f4b;
    border-radius: 6px;
    margin-top: 12px;
    padding-top: 8px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 4px;
    color: #9aa0ad;
}
QPushButton {
    background-color: #3a3f4b;
    color: #e6e6e6;
    border: 1px solid #4a5060;
    border-radius: 6px;
    padding: 6px 12px;
}
QPushButton:hover {
    background-color: #454b59;
}
QPushButton:pressed {
    background-color: #2f333d;
}
QPushButton:disabled {
    background-color: #2b2e36;
    color: #6b7180;
}
QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox {
    background-color: #2b2e36;
    color: #e6e6e6;
    border: 1px solid #4a5060;
    border-radius: 6px;
    padding: 4px 8px;
}
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: center right;
    width: 20px;
    border: none;
}
QComboBox::down-arrow {
    image: url(__ARROW_PATH__);
    width: 14px;
    height: 9px;
}
QComboBox QAbstractItemView {
    background-color: #2b2e36;
    color: #e6e6e6;
    selection-background-color: #4f8cff;
}
QPlainTextEdit, QTextEdit {
    background-color: #1f2127;
    color: #e6e6e6;
    border: 1px solid #3a3f4b;
    border-radius: 6px;
}
QListWidget {
    background-color: #1f2127;
    color: #e6e6e6;
    border: 1px solid #3a3f4b;
    border-radius: 6px;
}
QListWidget::item:selected {
    background-color: #4f8cff;
    color: #ffffff;
}
QSplitter::handle {
    background-color: #3a3f4b;
}
QProgressBar {
    background-color: #1f2127;
    border: 1px solid #3a3f4b;
    border-radius: 6px;
    text-align: center;
    color: #e6e6e6;
}
QProgressBar::chunk {
    background-color: #4f8cff;
    border-radius: 5px;
}
QLabel {
    background-color: transparent;
    color: #e6e6e6;
}
QMessageBox {
    background-color: #25282f;
}
"""
