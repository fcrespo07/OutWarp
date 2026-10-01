"""User-facing strings outside the web UI: tray, notifications, messages the
API hands the GUI, and the TUI.

The web UI has its own tables (ui/shared.jsx) and resolver
(ui-shared/i18n.jsx); both follow the same rule: the `language` setting is
"auto" or a code from LANGS, and a key a language lacks falls back to English.
With "auto", the GUI tells us what it resolved (`set_ui_language`) so tray,
notifications and error messages match the window exactly; without a GUI the
system locale decides.
"""

from __future__ import annotations

import locale
import os
import sys
import unicodedata

LANGS = ("en", "es")
# Each language in its own words, for pickers.
LANG_NAMES = {"en": "English", "es": "Español"}
FALLBACK_LANG = "en"

_ui_lang: str | None = None

def _catalog() -> dict[str, dict[str, str]]:
    from outwarp.locales import en, es

    return {"en": en.STRINGS, "es": es.STRINGS}


CATALOG = _catalog()


def set_ui_language(lang: str | None) -> None:
    """What the GUI resolved "auto" to; None forgets it."""
    global _ui_lang
    _ui_lang = lang if lang in LANGS else None


def _base(tag: str | None) -> str | None:
    if not tag:
        return None
    base = tag.replace("-", "_").split("_", 1)[0].split(".", 1)[0].lower()
    return base if base in LANGS else None


def system_lang() -> str:
    """The first supported language in the environment or OS locale."""
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        for tag in (os.environ.get(var) or "").split(":"):
            if tag in ("C", "POSIX"):
                continue
            if found := _base(tag):
                return found
    if sys.platform == "win32":
        try:
            import ctypes

            lcid = ctypes.windll.kernel32.GetUserDefaultUILanguage()  # type: ignore[attr-defined]
            if found := _base(locale.windows_locale.get(lcid)):
                return found
        except Exception:  # noqa: BLE001 — no locale is not an error
            pass
    try:
        found = _base(locale.getlocale()[0])
    except ValueError:
        found = None
    return found or FALLBACK_LANG


def resolve_lang(pref: str | None) -> str:
    if pref in LANGS:
        return pref  # type: ignore[return-value]
    return _ui_lang or system_lang()


def current_lang() -> str:
    """The language the `language` setting selects right now. OUTWARP_LANG in
    the environment wins (e.g. `OUTWARP_LANG=en outwarp tui`)."""
    if (forced := os.environ.get("OUTWARP_LANG")) in LANGS:
        return forced  # type: ignore[return-value]
    try:
        from outwarp.settings import load_settings

        pref = load_settings().get("language", "auto")
    except Exception:  # noqa: BLE001 — unreadable settings still get text
        pref = "auto"
    return resolve_lang(pref)


def t(key: str, lang: str | None = None, **params: object) -> str:
    """The string for `key` in `lang` (default: current_lang()), English if
    that language lacks it, the key itself if nobody has it."""
    lang = lang or current_lang()
    text = CATALOG.get(lang, {}).get(key) or CATALOG[FALLBACK_LANG].get(key, key)
    return text.format(**params) if params else text


def cell_width(text: str) -> int:
    """Terminal cells `text` takes: CJK (wide / fullwidth) characters take two."""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)


def pad(text: str, width: int) -> str:
    """`text` left-aligned in `width` terminal cells (str.ljust counts
    characters, which misaligns a TUI column as soon as a label is CJK)."""
    return text + " " * max(0, width - cell_width(text))
