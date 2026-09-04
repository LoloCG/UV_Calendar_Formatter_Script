import sys
from pathlib import Path

from core.ui import CalendarFormatterApp
from core.state_store import portable_state_path


def packaging_self_check() -> None:
    """Fail fast when a frozen build is missing release-time resources."""

    import tkinter as tk

    resource_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    stylesheet = resource_root / "core" / "ui" / "calendar_formatter.tcss"
    if not stylesheet.is_file():
        raise RuntimeError(f"Bundled stylesheet is missing: {stylesheet}")

    root = tk.Tk()
    root.withdraw()
    root.destroy()
    print("Packaging self-check passed: stylesheet and native dialogs are available.")


def main() -> int:
    if sys.argv[1:] == ["--self-check"]:
        packaging_self_check()
        return 0
    CalendarFormatterApp(config_path=portable_state_path()).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
