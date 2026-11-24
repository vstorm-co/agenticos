import { getLocaleFlag, getLocaleLabel, hasLocaleChoice, locales, type Locale } from "@/i18n";

/**
 * The language row on the walkthrough's first card (#2072).
 *
 * A new person meets the console in the deployment's default language, and the
 * account menu that changes it is one of the last places a first walk reaches.
 * driver.js draws its own popover, so the row is plain DOM appended to the
 * card's text; choosing a language re-renders the console in it and the walk
 * continues from the same card. A deployment with one locale has nothing to
 * choose, so the card gets no row.
 */
export function appendLanguageChoice(
  into: HTMLElement,
  current: Locale,
  label: string,
  choose: (locale: Locale) => void,
): void {
  if (!hasLocaleChoice) return;
  const row = document.createElement("div");
  row.setAttribute("role", "group");
  row.setAttribute("aria-label", label);
  row.className = "tour-language";
  for (const locale of locales) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = `${getLocaleFlag(locale)} ${getLocaleLabel(locale)}`;
    button.setAttribute("aria-pressed", String(locale === current));
    button.addEventListener("click", () => {
      if (locale !== current) choose(locale);
    });
    row.append(button);
  }
  into.append(row);
}
