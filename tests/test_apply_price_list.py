import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from apply_price_list import _dims, _first_number, _voltage_tokens, build_dict, MARKUP


def test_dims_parses_lxwxh():
    assert _dims("2094*1038*35") == (2094, 1038, 35)
    assert _dims("2094x1038x35mm") == (2094, 1038, 35)


def test_dims_none_when_incomplete():
    assert _dims(None) is None
    assert _dims("35mm") is None


def test_first_number_requires_whole_string_match():
    assert _first_number("18") == 18.0
    assert _first_number("18.5") == 18.5
    # "3-6" is a range, not a single value — must not silently pick one end
    assert _first_number("3-6") is None


def test_voltage_tokens_splits_multi_value_field():
    assert _voltage_tokens("12/60/65/70V") == {"12", "60", "65", "70V"}
    assert _voltage_tokens("12V") == {"12V"}


def test_build_dict_drops_ambiguous_keys():
    """Two price-list rows sharing a spec at different prices (e.g. the same
    12V*100AH GEL battery in two packagings, 56000 vs 48000 FCFA) must never
    resolve to either price — an AI quoting the wrong one is worse than
    saying 'contact us'."""
    pairs = [("100", 500), ("100", 500), ("200", 900), ("200", 950)]
    result = build_dict(pairs, lambda x: x)
    assert result == {"100": 500}
    assert "200" not in result


def test_markup_is_20_percent():
    assert MARKUP == 1.2
