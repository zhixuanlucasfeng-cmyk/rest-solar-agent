from app.agent.language_detector import detect_language


def test_detects_english():
    assert detect_language("What solar panels do you sell?") == "en"


def test_detects_french():
    assert detect_language("Quels panneaux solaires vendez-vous ?") == "fr"


def test_short_french_message():
    assert detect_language("Bonjour") == "fr"


def test_short_english_message():
    assert detect_language("Hello") == "en"


def test_mixed_defaults_to_detected():
    result = detect_language("Je veux buy solar panels")
    assert result in ("en", "fr")
