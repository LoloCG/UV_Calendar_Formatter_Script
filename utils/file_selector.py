import tkinter as tk
from tkinter import filedialog
import os
from pathlib import Path

def pick_file(
    title: str = "Select a file",
    initialdir: Path | None = None,
    filetypes: tuple[tuple[str, str], ...] = (("All files", "*.*"),),
) -> Path | None:
    """
    Opens a native file-open dialog and returns a Path, or None if canceled.
    No GUI window is shown and no mainloop is started.
    """
    root = tk.Tk()
    root.withdraw()  # hide the main window

    # On Windows, prevents a brief taskbar flash and puts dialog on top
    root.attributes("-topmost", True)
    root.update()  # apply 'topmost' before opening dialog

    try:
        path_str = filedialog.askopenfilename(
            title=title,
            initialdir=str(initialdir) if initialdir else None,
            filetypes=filetypes,
        )
    finally:
        root.destroy()

    return Path(path_str) if path_str else None


def pick_save_file(
    title: str = "Save file",
    initialdir: Path | None = None,
    initialfile: str | None = None,
    defaultextension: str = "",
    filetypes: tuple[tuple[str, str], ...] = (("All files", "*.*"),),
) -> Path | None:
    """Open a native Save As dialog and return its path, or None if canceled."""

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    root.update()

    try:
        path_str = filedialog.asksaveasfilename(
            title=title,
            initialdir=str(initialdir) if initialdir else None,
            initialfile=initialfile,
            defaultextension=defaultextension,
            filetypes=filetypes,
        )
    finally:
        root.destroy()

    return Path(path_str) if path_str else None


def default_desktop_directory() -> Path:
    """Return the user's desktop directory, falling back to their home."""

    home = Path.home()
    candidates: list[Path] = []

    onedrive = os.environ.get("OneDrive")
    if onedrive:
        candidates.append(Path(onedrive) / "Desktop")

    xdg_desktop = _read_xdg_desktop(home)
    if xdg_desktop is not None:
        candidates.append(xdg_desktop)

    candidates.append(home / "Desktop")
    return next((path for path in candidates if path.is_dir()), home)


def _read_xdg_desktop(home: Path) -> Path | None:
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))
    user_dirs = config_home / "user-dirs.dirs"
    try:
        lines = user_dirs.read_text(encoding="utf-8").splitlines()
    except (FileNotFoundError, OSError, UnicodeError):
        return None

    for line in lines:
        if not line.startswith("XDG_DESKTOP_DIR="):
            continue
        value = line.partition("=")[2].strip().strip('"')
        value = value.replace("$HOME", str(home))
        return Path(value).expanduser()
    return None
