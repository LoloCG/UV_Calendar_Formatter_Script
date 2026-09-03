def disable_parser_colorization() -> bool:
    """Disable optional parser diagnostics coloring when supported by ics.py."""

    try:
        from ics.grammar.parse import GRAMMAR
    except (ImportError, AttributeError):
        return False

    parser_config = getattr(GRAMMAR, "config", None)
    if parser_config is None or not hasattr(parser_config, "colorize"):
        return False

    parser_config.colorize = False
    return True
