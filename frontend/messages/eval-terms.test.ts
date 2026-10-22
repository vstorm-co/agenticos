import { describe, expect, it } from "vitest";

import de from "./de.json";
import pl from "./pl.json";

/**
 * That the eval screens say one word for one thing in Polish and German.
 *
 * The words are the glossary in `docs/howto/translate.md`, and they are the ones
 * the tabs already wear, so a sentence naming a tab names it as the tab does. Each
 * pattern is a form that reads as a second word for a glossary term - "case'ów"
 * for "przypadków", "Evale" for "Ewaluacje", "Draft" for "Entwurf". The product's
 * own nouns - agent, dataset, run, skill - stay English and are not matched.
 */

/** The namespaces an eval screen reads. The authoring assistant keeps its own copy. */
const SCOPE = [
  "evals.",
  "datasets.",
  "promotionGate.",
  "pages.runs.",
  "pages.agents.",
  "agents.",
  "triggers.",
  "knowledgeGaps.",
  "dashboard.widgets.",
  "onboarding.",
];

interface Mixed {
  pattern: RegExp;
  use: string;
}

const MIXED: Record<"pl" | "de", Mixed[]> = {
  pl: [
    { pattern: /case'|\bcases?\b/, use: "przypadek" },
    { pattern: /\b[Ee]val(e|a|i|em|ach|om|u|ów)?\b/, use: "ewaluacja, zakładka Ewaluacje" },
    { pattern: /\b[Rr]eview\b/, use: "przegląd" },
    { pattern: /\b[Dd]raft(u|em|y|ów|cie)?\b/, use: "wersja robocza" },
    { pattern: /\bBuild\b/, use: "Budowa" },
    { pattern: /\bActivity\b/, use: "Aktywność" },
    { pattern: /[Aa]systent(a|em)? AI/, use: "wsparcie AI" },
  ],
  de: [
    { pattern: /\bDraft\b/, use: "Entwurf" },
    { pattern: /\bEnvironments?\b/, use: "Umgebung" },
    { pattern: /\bJudges?\b/, use: "Bewerter" },
    { pattern: /\bReviews?\b/, use: "Prüfung" },
    // A build step is a build step; the tab is Bauen.
    { pattern: /\bBuild\b(?!-Schritt)/, use: "Bauen" },
    { pattern: /kaputt/, use: "verschlechtert" },
    { pattern: /\bActivity\b/, use: "Aktivität" },
  ],
};

type Catalog = { [key: string]: string | Catalog };

function flatten(catalog: Catalog, prefix = ""): [string, string][] {
  return Object.entries(catalog).flatMap(([key, value]) =>
    typeof value === "string" ? [[prefix + key, value]] : flatten(value, `${prefix}${key}.`),
  );
}

/** A message without its ICU argument names and case selectors, which are code, not copy. */
function prose(message: string): string {
  return message
    .replace(/\{\s*\w+\s*(?=[,}])/g, "{")
    .replace(/(select,|plural,|\})\s*=?\w+\s*\{/g, "$1 {");
}

function offences(catalog: Catalog, mixed: Mixed[]): string[] {
  return flatten(catalog)
    .filter(([key]) => SCOPE.some((prefix) => key.startsWith(prefix)))
    .flatMap(([key, value]) =>
      mixed
        .filter(({ pattern }) => pattern.test(prose(value)))
        .map(({ pattern, use }) => `${key} matches ${pattern} - write "${use}"`),
    );
}

describe("eval terminology", () => {
  it("reads past argument names and selectors to the words a person reads", () => {
    expect(prose("{cases, plural, one {# przypadek} other {# przypadków}}")).not.toMatch(/cases/);
    expect(prose("{kind, select, draft {Szkic} other {Wersja}}")).not.toMatch(/draft/);
    expect(prose("{count, plural, one {# case'a} other {# case'ów}}")).toMatch(/case'/);
  });

  it.each([
    ["pl", pl as Catalog, MIXED.pl],
    ["de", de as Catalog, MIXED.de],
  ])("in %s, says one word for one thing on the eval screens", (_locale, catalog, mixed) => {
    expect(offences(catalog, mixed)).toEqual([]);
  });
});
