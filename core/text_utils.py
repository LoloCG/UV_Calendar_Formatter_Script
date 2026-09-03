import unicodedata


def normalize_label(value: str | None) -> str:
    """Normalize a UV label for accent-insensitive policy comparisons."""

    text = (value or "").replace("\u00a0", " ").strip()
    text = " ".join(text.split())
    text = "".join(
        character
        for character in unicodedata.normalize("NFD", text)
        if not unicodedata.combining(character)
    )
    return text.casefold()
