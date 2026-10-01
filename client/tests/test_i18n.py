"""Strings outside the web UI: catalogs, language resolution, fallback."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from outwarp import i18n

_PKG = Path(i18n.__file__).parent


def test_every_language_has_exactly_the_english_keys() -> None:
    en = set(i18n.CATALOG["en"])
    for lang in i18n.LANGS:
        assert set(i18n.CATALOG[lang]) == en, lang


def test_placeholders_match_across_languages() -> None:
    # A translation that drops or renames {error} raises KeyError at runtime.
    fields = re.compile(r"{(\w+)}")
    for key, text in i18n.CATALOG["en"].items():
        for lang in i18n.LANGS:
            assert set(fields.findall(i18n.CATALOG[lang][key])) == set(fields.findall(text)), \
                (lang, key)


def test_every_key_the_code_uses_exists() -> None:
    used = set()
    for path in _PKG.rglob("*.py"):
        if "locales" in path.parts:
            continue
        used |= set(re.findall(r"""\b(?:tr|t)\(\s*["']([a-z_]+\.[a-z0-9_.]+)["']""",
                               path.read_text(encoding="utf-8")))
        # Keys kept in tables and passed to tr() later.
        used |= set(re.findall(
            r'"((?:tui|cli|svc|guiinst|uninst|dx)\.[a-z_]+\.[a-z0-9_]+|cli\.[a-z0-9_]+)"',
            path.read_text(encoding="utf-8"),
        ))
    missing = sorted(k for k in used if k not in i18n.CATALOG["en"])
    assert not missing


def test_missing_translation_falls_back_to_english(monkeypatch) -> None:
    monkeypatch.setitem(i18n.CATALOG, "es", {})
    assert i18n.t("tray.open", "es") == "Open OutWarp"
    assert i18n.t("no.such.key", "es") == "no.such.key"


def test_formats_parameters() -> None:
    assert i18n.t("notify.failed", "es", error="x") == "Fallo de conexión: x"


@pytest.mark.parametrize(("env", "expected"), [
    ({"LANG": "es_ES.UTF-8"}, "es"),
    ({"LANGUAGE": "fr:es", "LANG": "en_US.UTF-8"}, "es"),
    ({"LC_ALL": "C", "LANG": "es_MX.UTF-8"}, "es"),
    ({"LANG": "ja_JP.UTF-8"}, "en"),
])
def test_system_language_from_the_environment(monkeypatch, env, expected) -> None:
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        monkeypatch.delenv(var, raising=False)
    for var, value in env.items():
        monkeypatch.setenv(var, value)
    monkeypatch.setattr(i18n.locale, "getlocale", lambda: (None, None))
    monkeypatch.setattr(i18n.sys, "platform", "linux")
    assert i18n.system_lang() == expected


def test_explicit_setting_beats_the_window_and_the_system(monkeypatch) -> None:
    monkeypatch.setattr(i18n, "system_lang", lambda: "en")
    i18n.set_ui_language("es")
    try:
        assert i18n.resolve_lang("en") == "en"
        assert i18n.resolve_lang("auto") == "es"  # what the window resolved
    finally:
        i18n.set_ui_language(None)
    assert i18n.resolve_lang("auto") == "en"


def test_env_override(monkeypatch) -> None:
    monkeypatch.setenv("OUTWARP_LANG", "es")
    assert i18n.current_lang() == "es"
    monkeypatch.setenv("OUTWARP_LANG", "xx")
    monkeypatch.setattr(i18n, "system_lang", lambda: "en")
    assert i18n.current_lang() == "en"


def test_the_gui_can_tell_python_its_language() -> None:
    from outwarp.api import Api

    try:
        assert Api.set_ui_language(object(), "es") == {"ok": True, "lang": "es"}
    finally:
        i18n.set_ui_language(None)


def test_padding_counts_terminal_cells_not_characters() -> None:
    assert i18n.cell_width("total") == 5
    assert i18n.cell_width("客户端") == 6
    assert i18n.pad("客户端", 8) == "客户端  "
    assert i18n.pad("longer than width", 4) == "longer than width"
