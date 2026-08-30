from app.countries import COUNTRIES, DEFAULT_COUNTRY, normalize_country, is_valid_country


def test_country_set():
    assert COUNTRIES == ("CM", "NG", "SD", "ML")
    assert DEFAULT_COUNTRY == "CM"


def test_normalize_valid():
    assert normalize_country("NG") == "NG"
    assert normalize_country("ng") == "NG"
    assert normalize_country(" ml ") == "ML"


def test_normalize_invalid_falls_back():
    assert normalize_country(None) == "CM"
    assert normalize_country("") == "CM"
    assert normalize_country("US") == "CM"
    assert normalize_country("garbage") == "CM"


def test_is_valid_country():
    assert is_valid_country("SD") is True
    assert is_valid_country("sd") is True
    assert is_valid_country("XX") is False
    assert is_valid_country(None) is False
