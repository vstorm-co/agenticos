import { describe, expect, it } from "vitest";

import de from "./de.json";
import terms from "./eval-terms.json";
import pl from "./pl.json";

/**
 * That the eval screens say one word for one thing in Polish and German.
 *
 * The forms refused are in `eval-terms.json`, which `scripts/check_docs_glossary.py`
 * reads too for the pages about the same screens. The words are the glossary in
 * `docs/howto/translate.md`, and they are the ones
 * the tabs already wear, so a sentence naming a tab names it as the tab does. Each
 * pattern is a form that reads as a second word for a glossary term - "case'ów"
 * for "przypadków", "Evale" for "Ewaluacje", "Draft" for "Entwurf". The product's
 * own nouns - agent, dataset, run, skill - stay English and are not matched.
 */

interface Mixed {
  pattern: RegExp;
  use: string;
  /** Keys where the same word names something else. */
  except?: string[];
  /** Only these keys, when the word is wrong only in one sense. */
  within?: string[];
}

/** The namespaces an eval screen reads, and the ones naming the same things elsewhere. */
const SCOPE: string[] = terms.scope;

const MIXED: Record<"pl" | "de", Mixed[]> = {
  pl: terms.mixed.pl.map(compile),
  de: terms.mixed.de.map(compile),
};

function compile({
  pattern,
  ...rest
}: {
  pattern: string;
  use: string;
  except?: string[];
  within?: string[];
}): Mixed {
  return {
    pattern: new RegExp(pattern, "i"),
    use: rest.use,
    except: rest.except,
    within: rest.within,
  };
}

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

/** A catalog holding one message, at its dotted key. */
function single(key: string, value: string): Catalog {
  return key
    .split(".")
    .reduceRight<Catalog | string>((inner, part) => ({ [part]: inner }), value) as Catalog;
}

describe("the gate", () => {
  it.each([
    ["pl", "evals.live.answering", "Case'y, których wynik się zmieni"],
    ["pl", "evals.fields.fromRecordingsHint", "Case wzięty z rozmowy"],
    ["pl", "agents.testConnectionsHint", "Runy, łącznie z evalami"],
    ["pl", "onboarding.steps.flow-dataset-case-answers.body", "judge porównuje odpowiedź"],
    ["pl", "authoring.check.body", "Uruchamia dataset na drafcie"],
    ["pl", "agents.testPanelDraft", "Szkic"],
    ["pl", "knowledgeGaps.editDrafter", "Edytuj instrukcje draftera"],
    ["pl", "evals.review.send", "{count, plural, one {Wyślij do Review} other {Wyślij #}}"],
    ["de", "evals.estimate.judge", "Eval judge"],
    ["de", "datasets.generateIntro", "Der Case-Generator"],
    ["de", "evals.comparison.verdict.worse", "Macht Fälle kaputt"],
    ["de", "evals.draft", "{kind, select, a {Draft} other {Entwurf}}"],
  ] as const)("in %s, refuses %s reading %j", (locale, key, value) => {
    expect(offences(single(key, value), MIXED[locale])).not.toEqual([]);
  });

  it.each([
    ["pl", "knowledgeGaps.hasDraft", "Szkic"],
    ["pl", "datasets.proposalsBody", "Szkice czekają na akceptację"],
    ["pl", "agents.openInBuilder", "Otwórz w Builderze"],
    ["pl", "evals.answers", "{cases, plural, one {# przypadek} other {# przypadków}}"],
    ["de", "agents.reviewersTitle", "Run-Reviewer"],
    ["de", "agents.surfaceWidgetBody", "Ein Script-Tag, kein Build-Schritt."],
    ["de", "agents.approvalParksTheRun", "der Bot wirkt kaputt"],
  ] as const)("in %s, lets %s read %j", (locale, key, value) => {
    expect(offences(single(key, value), MIXED[locale])).toEqual([]);
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
