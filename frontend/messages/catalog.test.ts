import { describe, expect, it } from "vitest";

import en from "./en.json";
import pl from "./pl.json";

/**
 * That the catalog holds copy, and only copy.
 *
 * A translator opening `pl.json` translates whatever is in `en.json`, and until
 * this test existed 166 of those values were not sentences: 18 Tailwind class
 * lists read back through `cn(t("flexItemsStartGap"))`, and 148 fragments of
 * JavaScript source that nothing read at all - `"; case \"stats\": return"`,
 * `"(null); const [error, setError] = useState"`. Both arrived the same way: the
 * migration that moved copy into the catalog answered a false positive from the
 * guard - `scripts/check_i18n.py` then, `frontend/scripts/check-i18n.ts` since #395 -
 * by minting a key instead of marking the line `i18n-exempt`.
 *
 * The guard cannot see either, and the parser did not change that. Its offence sweep
 * skips a `className` attribute and a `cn()` argument, and a class list reaching `cn()`
 * through `t()` is neither; its `missingKeys` sweep only asks whether a key a component
 * reads exists, which it did. So the check has to run over the catalog rather than over the source,
 * and it is cheap: a value is copy, or it is one of two shapes nobody reads.
 */

/** Utilities that stand alone: `flex`, `border`, `group`. */
const BARE = new Set(
  (
    "group peer flex grid hidden block inline absolute relative fixed sticky contents isolate " +
    "truncate italic underline uppercase lowercase capitalize antialiased visible invisible " +
    "collapse static border rounded shadow ring outline transition filter grow shrink table"
  ).split(" "),
);

/** What a utility's first segment can be: `items-start`, `text-[10px]`, `sm:inline`. */
const PREFIX = new Set(
  (
    "items justify self content place gap space p px py pt pb pl pr m mx my mt mb ml mr " +
    "w h min max size text bg border rounded shadow overflow font leading tracking " +
    "transition ring outline opacity z top left right bottom inset shrink grow basis order " +
    "whitespace cursor select pointer backdrop animate duration ease delay translate scale " +
    "rotate skew origin object aspect columns col row divide list align table resize scroll " +
    "touch will filter blur brightness contrast grayscale invert saturate sepia from via to " +
    "fill stroke caret accent appearance sr line indent break hyphens float clear flex grid " +
    "inline place backface mix isolation snap sm md lg xl"
  ).split(" "),
);

const VARIANT = /^(?:[a-z0-9-]+|\[[^\]]+\]|data-\[[^\]]+\]):/;

function isUtility(token: string): boolean {
  let rest = token.replace(/^!/, "");
  while (VARIANT.test(rest)) rest = rest.slice(rest.indexOf(":") + 1);
  rest = rest.replace(/^-/, "");
  if (BARE.has(rest)) return true;
  const dash = rest.indexOf("-");
  return dash > 0 && PREFIX.has(rest.slice(0, dash));
}

/** Two or more tokens, every one of them a Tailwind utility. */
function isClassList(value: string): boolean {
  const tokens = value.split(/\s+/);
  return tokens.length > 1 && tokens.every(isUtility);
}

/**
 * Punctuation and keywords a sentence never holds, in any language this ships in.
 *
 * ICU is what makes the list this careful: `{count, plural, =1 {…} other {#…}}`
 * puts braces, `=` and `#` inside perfectly good copy, so none of those can be a
 * signal. Square brackets and a backslash can - and a backtick cannot, because
 * `mcp.authTokenHint` quotes a header name in one.
 *
 * The shape rules on the last line are for the fragments with no keyword in them
 * at all. A ternary between two JSX branches leaves `") : isUser ? ("`, and a
 * line the extractor cut mid-statement leaves `"; return"` and
 * `"; onChange: (value: Record"`: nothing a keyword catches, but no sentence
 * begins with a closing bracket, ends with an opening one, or ends on `return`.
 * Twenty-four values only these reach.
 */
const SOURCE = new RegExp(
  [
    "=>|===|!==|\\?\\?|\\?\\.|&&|\\|\\|",
    "\\buse(?:State|Effect|Memo|Ref|Callback)\\b",
    "\\bconst\\s+[[{\\w]|\\blet\\s+[[{\\w]+\\s*=|\\breturn\\s*[(;]",
    '\\breturn\\s+(?:null|true|false)\\b|\\bclassName\\b|\\bcase\\s+"|\\btypeof\\b',
    "[[\\]\\\\^~]",
    "\\bnull\\b|\\bundefined\\b|\\.(?:map|filter|join|push)\\(|\\.length\\b",
    "\\bset[A-Z]\\w*\\(",
    // `Custom (minutes):` is a label, so `):` at the end of a value is not a
    // signal - `) :` with something after it is.
    "^[;)\\]}]|[({]\\s*$|\\breturn\\s*$|\\)\\s*:\\s*\\S|\\bif\\s*\\(|:\\s*[A-Z]\\w*\\.",
  ].join("|"),
);

/** A `{noun}` parameter, with or without an ICU format after it. */
const NOUN = /\{\s*noun\s*[},]/;

/**
 * The punctuation a sentence never opens on, and so the signature of half of one.
 *
 * The cheapest of the three rules and the only one that finds a split sentence
 * without reading any JSX, which is the part #141 shows is hard: a value starting
 * `.`, `,`, `:` or `;` is the tail of something whose head is somewhere else, and
 * the head is almost always still hardcoded. A `…` opener is fine - `… and 3 more`
 * is a whole message.
 */
const TAIL = /^[.,:;](?!\w)/;

function entries(catalog: unknown, prefix = ""): [string, string][] {
  if (typeof catalog === "string") return [[prefix.replace(/\.$/, ""), catalog]];
  return Object.entries(catalog as Record<string, unknown>).flatMap(([key, value]) =>
    entries(value, `${prefix}${key}.`),
  );
}

/**
 * Both catalogues, and they are not equal evidence.
 *
 * **`en.json` is what proves the fix.** All 166 bad values were in it, and
 * reverting it alone fails these three with 18 class lists, 150 source fragments
 * and 8 `{noun}` messages named.
 *
 * **`pl.json` is a forward guard and passes on `main` too.** It holds 330 keys,
 * every one of them a translation somebody wrote by hand, and it never held any
 * of the three shapes - so the same three assertions over it assert nothing
 * about this change. They are here because the next locale is added by copying
 * `en.json` and translating downwards, which is exactly how a class list would
 * arrive in a second file having been fixed in the first.
 */
/** Tags a message opens without closing - see the assertion that uses it. */
function unclosedTags(value: string): string[] {
  return [...value.matchAll(/<([a-zA-Z][a-zA-Z0-9]*)>/g)]
    .map(([, tag]) => tag!)
    .filter((tag) => !value.includes(`</${tag}>`));
}

describe.each([
  ["en.json", en],
  ["pl.json", pl],
])("%s", (_name, catalog) => {
  const all = entries(catalog);

  it("holds no Tailwind class list", () => {
    const offenders = all.filter(([, value]) => isClassList(value)).map(([key]) => key);

    // Translating one hands `cn()` an opaque string it cannot tell from a class
    // name, and the component loses its border, its padding and its layout.
    expect(offenders).toEqual([]);
  });

  it("holds no fragment of source", () => {
    const offenders = all.filter(([, value]) => SOURCE.test(value)).map(([key]) => key);

    expect(offenders).toEqual([]);
  });

  it("interpolates no noun", () => {
    const offenders = all.filter(([, value]) => NOUN.test(value)).map(([key]) => key);

    // A noun the sentence around it has to agree with cannot be a parameter.
    // `{matched} of {total} {noun}` and `Who reaches this {noun}` read as
    // translated and rendered `3 of 40 skills` and `ten agent` under `pl`,
    // because only English leaves a noun undeclined beside a number or after a
    // demonstrative. The noun belongs inside an ICU `plural` or `select`, where
    // each locale writes the form it needs (#362).
    expect(offenders).toEqual([]);
  });

  it("opens no tag it does not close", () => {
    const offenders = all.filter(([, value]) => unclosedTags(value).length > 0).map(([key]) => key);

    // next-intl parses `<x>…</x>` as rich text, so an angle bracket around a
    // word is a *tag* and not prose. Unclosed, the message fails to parse and
    // `t()` renders the key path - `agents.surfacePageBody` in the middle of a
    // card, where "A link we serve, at /e/<key>" was meant to be. It is the one
    // failure that survives a green suite, because rendering a key throws
    // nothing.
    expect(offenders).toEqual([]);
  });

  it("holds no value that opens on punctuation", () => {
    const offenders = all.filter(([, value]) => TAIL.test(value)).map(([key]) => key);

    // No sentence begins with a full stop, so a value that does is the second
    // half of one - and the first half is still in the JSX, in English, under
    // every locale. Eleven were: `. Pick one it does, …` beside `This connection
    // no longer allows`, `, so the label carries the same classes.`,
    // `, error:`. The whole sentence is one message with a tag in it, read with
    // `t.rich` (#425).
    expect(offenders).toEqual([]);
  });
});

describe("the rules themselves", () => {
  it("reads a class list and a source fragment as what they are", () => {
    expect(isClassList("flex items-start gap-3 rounded-xl border p-4 transition-colors")).toBe(
      true,
    );
    expect(isClassList("group absolute top-0 left-0 z-20 h-full w-1.5 cursor-col-resize")).toBe(
      true,
    );
    expect(SOURCE.test('; case "stats": return')).toBe(true);
    expect(SOURCE.test("(null); const [error, setError] = useState")).toBe(true);
    expect(SOURCE.test(") : isUser ? (")).toBe(true);
    expect(SOURCE.test("; return")).toBe(true);
    expect(SOURCE.test("; onChange: (value: Record")).toBe(true);
  });

  it("reads copy as copy, ICU and markdown included", () => {
    expect(isClassList("Showing 1 of 57 documents")).toBe(false);
    expect(SOURCE.test("{count, plural, =1 {1 chunk} other {# chunks}}")).toBe(false);
    expect(SOURCE.test("A static credential, sent as `Authorization: Bearer`.")).toBe(false);
    expect(SOURCE.test("Files will be added to <strong>{name}</strong>")).toBe(false);
    expect(SOURCE.test("Custom (minutes):")).toBe(false);
    expect(SOURCE.test(". Pick one it does, or the agent fails on its first tool call.")).toBe(
      false,
    );
  });

  it("reads an unclosed tag as one, and a closed pair as rich text", () => {
    expect(unclosedTags("A link we serve, at /e/<key>.")).toEqual(["key"]);
    expect(unclosedTags("Files will be added to <strong>{name}</strong>")).toEqual([]);
    expect(unclosedTags("Use <code>--force</code> and read <em>this</em> first")).toEqual([]);
    expect(unclosedTags("a < b, and 3 > 2")).toEqual([]);
  });

  it("tells the tail of a sentence from a whole one", () => {
    expect(TAIL.test(". Pick one it does, or the agent fails on its first tool call.")).toBe(true);
    expect(TAIL.test(", so the label carries the same classes.")).toBe(true);
    expect(TAIL.test(", error:")).toBe(true);
    expect(TAIL.test("Custom (minutes):")).toBe(false);
    expect(TAIL.test("…and {count} more")).toBe(false);
    expect(TAIL.test(".env is never committed")).toBe(false);
  });
});
