import { TRANSLATIONS } from "./translations.js";

export const LANGUAGES = ["en", "pl", "de", "tr"];
/** @param {string} value @returns {string} */
export function languageOf(value) {
  const candidate = String(value).split("-")[0].toLowerCase();
  return LANGUAGES.includes(candidate) ? candidate : "en";
}
/** @param {string} text @param {string} language @returns {string} */
export function translated(text, language) {
  const normalized = text.replace(/\s+/g, " ").trim();
  const exact = TRANSLATIONS[normalized]?.[language];
  if (exact)
    return `${text.match(/^\s*/)?.[0] ?? ""}${exact}${text.match(/\s*$/)?.[0] ?? ""}`;
  const prefix = "Preparing AgenticOS…";
  if (normalized.startsWith(prefix))
    return `${TRANSLATIONS[prefix]?.[language] ?? prefix}${normalized.slice(prefix.length)}`;
  return text;
}

/** Only shell-owned UI is translated; instance names, errors and provider detail stay untouched. */
/** @param {(command: string, args: Record<string, string>) => Promise<unknown>} invoke @returns {Promise<void>} */
export function startLanguage(invoke) {
  const select = document.getElementById("language");
  if (!(select instanceof HTMLSelectElement))
    throw new Error("Language control is missing");
  let language = languageOf(navigator.language);
  try {
    language = languageOf(
      localStorage.getItem("agenticos:start-language") || language,
    );
  } catch {
    /* A refused preference store does not prevent setup. */
  }
  /** @type {WeakMap<Node, {source: string, rendered: string}>} */
  const remembered = new WeakMap();
  /** @param {HTMLElement} root */
  function apply(root) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
      if (
        node.parentElement?.closest(
          "script, style, #language, .instance-list, .error, [data-progress-detail]",
        )
      )
        continue;
      const previous = remembered.get(node);
      const source =
        previous && node.textContent === previous.rendered
          ? previous.source
          : (node.textContent ?? "");
      const rendered = translated(source, language);
      remembered.set(node, { source, rendered });
      if (node.textContent !== rendered) node.textContent = rendered;
    }
    for (const input of root.querySelectorAll?.("input[placeholder]") ?? []) {
      const source = input.dataset.originalPlaceholder ?? input.placeholder;
      input.dataset.originalPlaceholder = source;
      input.placeholder = translated(source, language);
    }
    document.documentElement.lang = language;
  }
  const observer = new MutationObserver(() => apply(document.body));
  observer.observe(document.body, {
    subtree: true,
    childList: true,
    characterData: true,
  });
  /** @param {string} value */
  async function choose(value) {
    language = languageOf(value);
    select.value = language;
    try {
      localStorage.setItem("agenticos:start-language", language);
    } catch {
      /* Keep the current choice for this window. */
    }
    apply(document.body);
    await invoke("set_onboarding_language", { language });
  }
  select.addEventListener("change", () => {
    void choose(select.value).catch((error) =>
      invoke("page_error", { message: String(error) }),
    );
  });
  return choose(language);
}
