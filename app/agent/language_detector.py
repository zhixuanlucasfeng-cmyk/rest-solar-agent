import re
from langdetect import detect, LangDetectException

_FR_RE = re.compile(
    r"\b(bonjour|bonsoir|merci|oui|non|votre|notre|vous|nous|est|les|des"
    r"|une|pour|avec|sur|dans|que|qui|quoi|quand|où|comment|combien|quel"
    r"|quelle|prix|panneau|solaire|batterie|onduleur|livraison|garantie"
    r"|achat|vouloir|voudrais|avez|avons|sommes|êtes|panneau)\b",
    re.IGNORECASE,
)


def detect_language(text: str) -> str:
    """Return 'fr' or 'en'. Uses langdetect with regex fallback for short messages."""
    try:
        lang = detect(text)
        if lang in ("fr", "en"):
            return lang
    except LangDetectException:
        pass
    return "fr" if _FR_RE.search(text) else "en"
