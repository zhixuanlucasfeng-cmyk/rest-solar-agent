COUNTRIES: tuple[str, ...] = ("CM", "NG", "SD", "ML")
DEFAULT_COUNTRY: str = "CM"


def is_valid_country(value: str | None) -> bool:
    return isinstance(value, str) and value.strip().upper() in COUNTRIES


def normalize_country(value: str | None) -> str:
    if isinstance(value, str) and value.strip().upper() in COUNTRIES:
        return value.strip().upper()
    return DEFAULT_COUNTRY
