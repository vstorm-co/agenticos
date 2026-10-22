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

/** The namespaces an eval screen reads, the authoring assistant's card among them. */
const SCOPE = [
  "evals.",
  "authoring.",
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
  /** Keys where the same word names something else. */
  except?: string[];
  /** Only these keys, when the word is wrong only in one sense. */
  within?: string[];
}

/** Where "draft" is the content written for a knowledge gap, not an unpublished agent. */
const GAP_DRAFTS = ["knowledgeGaps.", "agents.drafterKind", "onboarding.steps.agents-system."];

const MIXED: Record<"pl" | "de", Mixed[]> = {
  pl: [
    { pattern: /case'|\bcase(s|y|ów|a|u|em|ach|ami|om)?\b/i, use: "przypadek" },
    { pattern: /\beval(e|a|i|u|em|om|ów|ach|ami)?\b/i, use: "ewaluacja, zakładka Ewaluacje" },
    { pattern: /\breview(u|y|em|ie|ów)?\b/i, use: "przegląd" },
    { pattern: /\bdraf(t|tu|tem|ty|tów|cie)\b/i, use: "wersja robocza" },
    {
      pattern: /\bszkic(u|em|e|ów|ach|ami)?\b/i,
      use: "wersja robocza",
      except: GAP_DRAFTS,
    },
    { pattern: /\bjudge\b/i, use: "sędzia" },
    { pattern: /\bbuild\b/i, use: "Budowa" },
    { pattern: /\bactivity\b/i, use: "Aktywność" },
    { pattern: /\bpublish\b/i, use: "Opublikuj" },
    { pattern: /asystent(a|em|owi)? AI/i, use: "wsparcie AI" },
  ],
  de: [
    { pattern: /\bcases?\b/i, use: "Fall" },
    { pattern: /\bdrafts?\b/i, use: "Entwurf" },
    { pattern: /\benvironments?\b/i, use: "Umgebung" },
    { pattern: /\bjudges?\b/i, use: "Bewerter" },
    { pattern: /\breviews?\b/i, use: "Prüfung" },
    // A build step is a build step; the tab is Bauen.
    { pattern: /\bbuild\b(?!-Schritt)/i, use: "Bauen" },
    { pattern: /\bactivity\b/i, use: "Aktivität" },
    // What a verdict says of cases; a page that looks broken may still read "kaputt".
    {
      pattern: /kaputt/i,
      use: "verschlechtert",
      within: [
        "evals.",
        "onboarding.offer.test-change.",
        "onboarding.steps.eval-",
        "onboarding.steps.flow-test-",
      ],
    },
  ],
};

type Catalog = { [key: string]: string | Catalog };

function flatten(catalog: Catalog, prefix = ""): [string, string][] {
  return Object.entries(catalog).flatMap(([key, value]) =>
    typeof value === "string" ? [[prefix + key, value]] : flatten(value, `${prefix}${key}.`),
  );
}

/**
 * The words a person reads in an ICU message: its text and the text of every
 * branch, without argument names, argument types, selectors or rich-text tags.
 */
function prose(message: string): string {
  let at = 0;
  const branch = (): string => {
    let out = "";
    while (at < message.length && message[at] !== "}") {
      if (message[at] === "{") {
        at += 1;
        out += ` ${argument()} `;
      } else {
        out += message[at];
        at += 1;
      }
    }
    return out;
  };
  const argument = (): string => {
    const head = /^\s*\w+\s*(,\s*\w+\s*)?(,)?/.exec(message.slice(at));
    at += head?.[0].length ?? 0;
    let out = "";
    // A select or plural: selectors, each followed by its own branch, until the closing brace.
    for (;;) {
      const selector = /^\s*(=?\w+)?\s*/.exec(message.slice(at));
      at += selector?.[0].length ?? 0;
      if (message[at] !== "{") break;
      at += 1;
      out += ` ${branch()} `;
      at += 1;
    }
    at += 1;
    return out;
  };
  let out = "";
  while (at < message.length) {
    out += branch();
    at += 1;
  }
  return out.replace(/<\/?\w+>/g, " ");
}

function offences(catalog: Catalog, mixed: Mixed[]): string[] {
  return flatten(catalog)
    .filter(([key]) => SCOPE.some((prefix) => key.startsWith(prefix)))
    .flatMap(([key, value]) =>
      mixed
        .filter(({ except = [] }) => !except.some((prefix) => key.startsWith(prefix)))
        .filter(({ within = [""] }) => within.some((prefix) => key.startsWith(prefix)))
        .filter(({ pattern }) => pattern.test(prose(value)))
        .map(({ pattern, use }) => `${key} matches ${pattern} - write "${use}"`),
    );
}

describe("prose", () => {
  it("leaves out argument names, types and selectors", () => {
    const read = prose("{cases, plural, one {# przypadek} other {# przypadków}} {total, number}");
    expect(read).not.toMatch(/cases|plural|one|other|total|number/);
    expect(read).toMatch(/przypadek/);
    expect(prose("{kind, select, draft {Szkic} other {Wersja}}")).not.toMatch(/draft/);
  });

  it("keeps every word a person reads, in a branch or between placeholders", () => {
    expect(prose("{kind, select, a {Draft} other {x}}")).toMatch(/Draft/);
    expect(prose("{name} review {date}")).toMatch(/review/);
    expect(prose("{count, plural, one {# case'a} other {# case'ów}}")).toMatch(/case'/);
    expect(prose("Sent to <b>review</b>")).toMatch(/review/);
  });
});

describe("eval terminology", () => {
  it.each([
    ["pl", pl as Catalog, MIXED.pl],
    ["de", de as Catalog, MIXED.de],
  ])("in %s, says one word for one thing on the eval screens", (_locale, catalog, mixed) => {
    expect(offences(catalog, mixed)).toEqual([]);
  });
});
