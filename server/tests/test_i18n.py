"""Server strings outside the web UI: catalogs, fallback, what the code uses."""
from __future__ import annotations

import re
from pathlib import Path

from outwarp_server import i18n

_PKG = Path(i18n.__file__).parent


def test_every_language_has_exactly_the_english_keys() -> None:
    en = set(i18n.CATALOG["en"])
    for lang in i18n.LANGS:
        assert set(i18n.CATALOG[lang]) == en, lang


def test_placeholders_match_across_languages() -> None:
    fields = re.compile(r"{(\w+)}")
    for key, text in i18n.CATALOG["en"].items():
        for lang in i18n.LANGS:
            assert set(fields.findall(i18n.CATALOG[lang][key])) == set(fields.findall(text)), \
                (lang, key)


def test_every_key_the_code_uses_exists() -> None:
    used: set[str] = set()
    for path in _PKG.rglob("*.py"):
        if "locales" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        used |= set(re.findall(r"""\b(?:tr|t)\(\s*["']([a-z_]+\.[a-z0-9_.]+)["']""", text))
        used |= set(re.findall(r'"((?:tui|tray)\.[a-z_]+\.?[a-z0-9_]*)"', text))
    assert used
    assert sorted(k for k in used if k not in i18n.CATALOG["en"]) == []


def test_missing_translation_falls_back_to_english(monkeypatch) -> None:
    monkeypatch.setitem(i18n.CATALOG, "es", {})
    assert i18n.t("tray.quit", "es") == "Stop and quit"


def test_language_setting_is_read_from_the_gui_settings(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("OUTWARP_LANG")
    monkeypatch.setattr("outwarp_server.config.default_config_dir", lambda: tmp_path)
    (tmp_path / "gui_settings.json").write_text('{"language": "es"}', encoding="utf-8")
    assert i18n.current_lang() == "es"


def test_the_desktop_window_sets_the_tray_language_but_the_panel_cannot() -> None:
    from outwarp_server.api import Api
    from outwarp_server.web_server import ALLOWED_METHODS

    try:
        assert Api.set_ui_language(object(), "es") == {"ok": True}
        assert i18n.resolve_lang("auto") == "es"
    finally:
        i18n.set_ui_language(None)
    assert "set_ui_language" not in ALLOWED_METHODS


def test_padding_counts_terminal_cells_not_characters() -> None:
    assert i18n.pad("在线", 9) == "在线     "
    assert i18n.cell_width(i18n.pad("online", 9)) == 9
