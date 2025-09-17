import tkinter as tk
from tkinter import filedialog
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