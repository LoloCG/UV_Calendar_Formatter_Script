from core.ui import CalendarFormatterApp
from core.state_store import portable_state_path


def main():
    CalendarFormatterApp(config_path=portable_state_path()).run()


if __name__ == "__main__":
    main()
