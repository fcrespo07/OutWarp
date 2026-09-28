import { beforeAll, describe, expect, it } from "vitest";
import { loadUi } from "./load.js";

let i18n, STR, DS_STR;
beforeAll(() => {
  i18n = loadUi("ui-shared/i18n.jsx").OWi18n;
  STR = loadUi("client/outwarp/ui/shared.jsx").STR;
  DS_STR = loadUi("server/outwarp_server/ui/dash-data.jsx").DS_STR;
});

describe("resolveLang", () => {
  it("honours an explicit choice", () => {
    expect(i18n.resolveLang("es", ["en-US"])).toBe("es");
  });

  it("follows the system on auto, by base language", () => {
    expect(i18n.resolveLang("auto", ["es-ES", "en"])).toBe("es");
    expect(i18n.resolveLang("auto", ["fr-FR", "en-GB"])).toBe("en");
    expect(i18n.resolveLang(undefined, ["es_MX"])).toBe("es");
  });

  it("falls back to English for anything unsupported", () => {
    expect(i18n.resolveLang("auto", ["ja-JP"])).toBe("en");
    expect(i18n.resolveLang("klingon", [])).toBe("en");
    expect(i18n.resolveLang("auto", [undefined])).toBe("en");
  });
});

describe("stringsFor", () => {
  const table = { en: { a: "A", b: "B" }, es: { a: "a-es" } };

  it("fills a missing key from English", () => {
    const es = i18n.stringsFor(table, "es");
    expect(es.a).toBe("a-es");
    expect(es.b).toBe("B");
    expect(i18n.missingKeys(table, "es")).toEqual(["b"]);
  });

  it("serves English for a language with no table yet", () => {
    expect(i18n.stringsFor(table, "fr").a).toBe("A");
  });
});

// Every language has every key: a missing one would silently show English.
describe.each([
  ["client GUI (STR)", () => STR],
  ["server dashboard (DS_STR)", () => DS_STR],
])("%s", (_name, table) => {
  it.each(["en", "es"])("covers every language in OWi18n.LANGS (%s)", (lang) => {
    expect(i18n.LANGS).toContain(lang);
    expect(i18n.missingKeys(table(), lang)).toEqual([]);
  });

  it("has no key English lacks", () => {
    const en = new Set(Object.keys(table().en));
    for (const lang of i18n.LANGS) {
      expect(Object.keys(table()[lang]).filter((k) => !en.has(k))).toEqual([]);
    }
  });
});
