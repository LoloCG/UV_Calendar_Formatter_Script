import sys
from pathlib import Path


def _configure_windows_terminal_encoding() -> None:
    """Use UTF-8 for Textual's box-drawing and block characters on Windows."""

    if sys.platform != "win32":
        return

    try:
        import ctypes

        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
    except (AttributeError, OSError):
        pass

    configured_streams: set[int] = set()
    for stream in (sys.stdout, sys.stderr, sys.__stdout__, sys.__stderr__):
        if stream is None or id(stream) in configured_streams:
            continue
        configured_streams.add(id(stream))
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


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
    _configure_windows_terminal_encoding()
    if sys.argv[1:] == ["--self-check"]:
        packaging_self_check()
        return 0

    from core.state_store import portable_state_path
    from core.ui import CalendarFormatterApp

    CalendarFormatterApp(config_path=portable_state_path()).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
