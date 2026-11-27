import { afterEach, expect, it, vi } from "vitest";
import { TRANSLATIONS } from "../../../desktop/ui/translations.js";
import { languageOf, startLanguage, translated } from "../../../desktop/ui/language.js";

afterEach(() => {
  localStorage.clear();
  document.body.innerHTML = "";
  vi.restoreAllMocks();
});
it("recognizes supported languages without accepting a URL as a locale", () => {
  expect(languageOf("pl-PL")).toBe("pl");
  expect(languageOf("TR-tr")).toBe("tr");
  expect(languageOf("nl-BE")).toBe("nl");
  expect(languageOf("https://example.com")).toBe("en");
  expect(translated("Get started", "pl")).toBe("Zacznij");
  expect(translated(" Get started ", "pl")).toBe(" Zacznij ");
  expect(translated("Preparing AgenticOS… 50%", "de")).toBe("AgenticOS wird vorbereitet… 50%");
  expect(translated("Welcome to AgenticOS", "nl")).toBe("Welkom bij AgenticOS");
  expect(translated("Provider detail", "pl")).toBe("Provider detail");
});
it("localizes shell controls and passes the language to the native connection", async () => {
  localStorage.setItem("agenticos:start-language", "pl");
  document.body.innerHTML =
    '<select id="language"><option value="en">English</option><option value="pl">Polski</option></select><h1>Get started</h1><input placeholder="Add now or later"><div class="instance-list">Get started</div><p class="error">Get started</p>';
  const invoke = vi.fn().mockResolvedValue(undefined);
  await startLanguage(invoke);
  expect(document.documentElement.lang).toBe("pl");
  expect(document.querySelector("h1")?.textContent).toBe("Zacznij");
  expect(document.querySelector("input")?.placeholder).toBe("Dodaj teraz lub później");
  expect(document.querySelector(".instance-list")?.textContent).toBe("Get started");
  expect(document.querySelector(".error")?.textContent).toBe("Get started");
  expect(invoke).toHaveBeenCalledWith("set_onboarding_language", { language: "pl" });
});

it.each(["pl", "de", "tr", "pt", "nl"] as const)(
  "translates the complete native catalog in %s",
  (locale) => {
    for (const [source, translations] of Object.entries(TRANSLATIONS)) {
      expect(translations, source).toHaveProperty(locale);
      expect(translated(source, locale), source).toBeTruthy();
    }
  },
);
