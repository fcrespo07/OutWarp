// Language selection shared by the client GUI and the server dashboard / web
// panel (scripts/build_ui.py bundles this file into both).
//
// The setting is "auto" (follow the system or browser) or a language code.
// Any key a language lacks falls back to English, so a half-translated
// language never shows a blank or an `undefined`.

const LANGS = ["en", "es"];
const FALLBACK_LANG = "en";
// Each language's name in itself, for the selector.
const LANG_NAMES = { en: "English", es: "Español" };

function resolveLang(pref, systemLangs) {
  if (pref && pref !== "auto" && LANGS.includes(pref)) return pref;
  for (const tag of systemLangs || []) {
    const base = String(tag || "").toLowerCase().split(/[-_]/)[0];
    if (LANGS.includes(base)) return base;
  }
  return FALLBACK_LANG;
}

function systemLangs() {
  const nav = window.navigator || {};
  return nav.languages && nav.languages.length ? nav.languages : [nav.language];
}

const merged = new Map();
function stringsFor(table, lang) {
  let byLang = merged.get(table);
  if (!byLang) { byLang = {}; merged.set(table, byLang); }
  if (!byLang[lang]) byLang[lang] = { ...table[FALLBACK_LANG], ...(table[lang] || {}) };
  return byLang[lang];
}

// Keys English has and `lang` lacks: what a translator still has to do.
function missingKeys(table, lang) {
  const own = table[lang] || {};
  return Object.keys(table[FALLBACK_LANG]).filter((k) => !(k in own));
}

window.OWi18n = { LANGS, LANG_NAMES, FALLBACK_LANG, resolveLang, systemLangs, stringsFor, missingKeys };
