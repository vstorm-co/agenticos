/**
 * Refuse copy that a component wrote itself.
 *
 * Every user-facing string in the frontend comes from `messages/en.json` through
 * `next-intl`, and the rule survives exactly as long as something checks it: a
 * convention that is only written down gets broken by the next feature, silently,
 * and the Polish UI ships half in English.
 *
 * This is the same policy the Python guard enforced, read through a parser instead
 * of ten regexes over source text. That swap is the point rather than a detail.
 * `scripts/check_i18n.py` was patched for a new shape four times - #199, #246, #249,
 * #314 - and each fix was correct: the pattern was the problem. Reading a `.tsx` file
 * as text means deciding, per candidate, whether you are looking at TypeScript or
 * JSX, so every rule carried a threshold or an exclusion standing in for a parse and
 * the next shape fell between two of them. The last one was one word wide:
 * `` aria-label={`Remove ${source.name}`} `` sat below a two-word threshold that
 * existed to keep `` `audience${key}Hint` `` out, and 53 strings in 32 files rendered
 * in English under `pl` (#395).
 *
 * A parser has no line to read and no threshold to tune. What each rule looks at:
 *
 * * **a JSX phrase** - the text and interpolations between two elements, taken
 *   together. `Owned by {email}`, `{n} runs`, `Rotate {name}`, `{used} of {max} used`
 *   and a paragraph the formatter broke over three lines are all one phrase with one
 *   rule, where the regexes needed `JSX_TEXT`, `MIXED`, `COUNT` and `LEAD` and still
 *   missed a plain node split across lines (#141);
 * * **a readable attribute** - `placeholder`, `aria-label`, `title`, `alt` and the
 *   label-ish props components take. Still a fixed list: a parser can read a prop's
 *   value but not decide that a name it has never seen is read by a person;
 * * **a template literal**, where copy hides best - it is not a text node, not an
 *   attribute and not a plain string. Whitespace is the discriminator the two-word
 *   threshold was standing in for: a word with a space between it and the
 *   interpolation is prose, an identifier assembled by interpolation has none;
 * * **a string literal** holding a sentence - `{busy ? "Saving…" : "Save"}`, a
 *   sentence pushed into an array, `toast.success("…")`;
 * * **a plural somebody rolled by hand** - `{n} file{n === 1 ? "" : "s"}`, which is a
 *   sentence only English can build that way.
 *
 * What it deliberately does not look at:
 *
 * * tests, which assert the copy and must name it;
 * * `src/app/[locale]/(dashboard)/dev/**`, a playground for looking at components
 *   that is not part of the product;
 * * anything a person never reads - `className`, `href`, `data-*`, `id`, `type`;
 * * **a `.ts` file**, for the offence sweep only. A parser reads one by construction,
 *   which is what #446 needs and #446 is 406 offences across 91 files: a copy
 *   migration of its own size. The two catalog rules below already read every `.ts`
 *   file, because a hook's toast is copy.
 *
 * False positives get an inline `{/* i18n-exempt: why *␀/}` or a trailing
 * `// i18n-exempt: why`. The comment is required to carry a reason, because "this one
 * is fine" is the sentence that turns a gate into a rubber stamp. A comment is
 * invisible to the parser, so nothing has to blank one out first - which is one of
 * the two reasons `readable()` and `mask_generics()` have no counterpart here.
 *
 * Two more rules read the catalog and ask a question of the source, rather than
 * reading the source and asking a question of it:
 *
 * * `unreadKeys` - a key nothing reads. 141 of them once, 82 with a Polish
 *   translation somebody had written for nobody. The extraction pass sometimes lifted
 *   a string into the catalog and left the component reading the literal, so both
 *   halves looked clean while the English stayed on screen (#425);
 * * `duplicatedInSource` - a message whose words are also written out somewhere. That
 *   is the other half of the same defect, and it is what points at the line.
 *
 * **A false positive takes an exemption. It never takes a key.** Answering one by
 * moving the offending text into `messages/en.json` silences the guard and hands a
 * translator something nobody reads: the migration that first ran this check did
 * exactly that 166 times, filing 18 Tailwind class lists and 148 fragments of
 * JavaScript source under keys with names like `caseStatsReturn` (#348).
 * `messages/catalog.test.ts` refuses both shapes.
 *
 * Run with `bun run check:i18n`, or `--all` to list a whole backlog.
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import ts from "typescript";

const HERE = dirname(fileURLToPath(import.meta.url));
const FRONTEND = resolve(HERE, "..");
const ROOT = resolve(FRONTEND, "..");
const SRC = join(FRONTEND, "src");
const CATALOG = join(FRONTEND, "messages", "en.json");

const SKIPPED_DIRS = ["/dev/"];
const SKIPPED_NAMES = [".test.tsx", ".test.ts", ".spec.ts", ".stories.tsx", ".generated.ts"];

/**
 * Props a component renders for a person to read.
 *
 * Still a fixed list, and still the weakness of the rule: copy passed through a name
 * that is not here is copy nothing reports, and it stays invisible until somebody
 * notices it in English under `pl`. `noun` and `term` were added after exactly that
 * (#362) - `<Pager noun="skills">` at six call sites and `<Fact term="Chunking">` at
 * four, all rendered verbatim in every locale.
 *
 * A parser could read every prop's value instead of trusting its name, and that is
 * not the same rule: `variant="destructive"`, `side="bottom"` and `type="submit"` are
 * string-valued props nobody reads, so the widening would trade this list for a list
 * of exclusions the same length. What the parser does buy is the *value*: a template
 * literal or a ternary in a readable prop is read here, where `ATTR` matched a
 * double-quoted literal alone.
 */
export const READABLE_ATTRS = [
  "placeholder",
  "aria-label",
  "alt",
  "title",
  "label",
  "description",
  "emptyMessage",
  "confirmLabel",
  "cancelLabel",
  "submitLabel",
  "heading",
  "subtitle",
  "noun",
  "term",
];

const TOAST_METHODS = ["success", "error", "info", "warning", "message"];
/** Calls whose string arguments are Tailwind classes rather than anything readable. */
const CLASS_CALLS = ["cn", "clsx", "cva", "cx", "twMerge"];
/** Attributes whose string value is markup, however many words it holds. */
const UNREADABLE_ATTRS = ["className", "class"];

const WORDS = /[A-Za-z]{2,}/g;
const EXEMPT = /i18n-exempt:\s*\S/;
/**
 * A word-bearing string that is still not copy: an icon name, a CSS-ish token, a
 * path, a MIME type, a locale tag. Matched whole, so "Save changes" never hits it.
 */
const NOT_COPY =
  /^(?:[a-z0-9-]+(?:\/[a-z0-9.*+-]+)+|[a-z]+(?:-[a-z0-9]+)+|[A-Za-z]+\.[A-Za-z]{2,4}|https?:\/\/\S+|&[a-z]+;|[A-Z_]{2,}|\d+(?:\.\d+)?\s*\w{0,3})$/;
/** An HTML entity is punctuation somebody spelled out, not a word. */
const ENTITY = /&(?:[a-zA-Z]+|#\d+);/g;
/**
 * A URL, a query string, a CSS value, a header - built by interpolation, read by a
 * machine.
 *
 * A bare `?` used to be on this list, and it exempted every question in the tree:
 * `` `Disconnect "${connection.name}"?` `` is a confirm dialog, not a query string, and
 * it sat behind the character that was standing in for one. A question mark only says
 * "machine" next to an `=`, which `[=]` already catches on its own.
 */
const MACHINE_READ = /[/&=<>#]|\b(?:px|rem|deg|vh|vw|attachment)\b/;
/**
 * A unit, and the answer to the fourteen number-and-unit formatters #395 left open -
 * `` `${Math.round(bytes / 1024)} KiB` ``,
 * `` `${seconds / 60} min` ``,
 * `` `HTTP ${r.status}` ``.
 * They take a rule rather than a message or fourteen exemptions,
 * because a unit is not translated - `KiB` is `KiB` in every locale, and a key holding
 * it hands a translator a symbol they must not touch. A phrase whose every word is a
 * unit or an all-caps token is a formatter; one word beside a unit makes it a sentence
 * again, so `` `${n} files left` `` is still refused.
 */
const UNITS = new Set([
  "px",
  "rem",
  "em",
  "vh",
  "vw",
  "deg",
  "ms",
  "s",
  "min",
  "h",
  "hr",
  "d",
  "B",
  "kB",
  "KB",
  "MB",
  "GB",
  "TB",
  "KiB",
  "MiB",
  "GiB",
  "TiB",
  // A context window is measured in `ctx` on the model picker's badge, the way
  // storage is measured in KiB. Jargon rather than SI, and the reason the list is a
  // list: it is short, and each entry is a token this product actually renders.
  "ctx",
]);
/** A token a machine wrote: a unit, or an acronym that reads the same everywhere. */
const MACHINE_WORD = /^[A-Z0-9_]+$/;
/**
 * What `NOT_A_SENTENCE` kept out of the string-literal rule: a label built from title
 * case around a separator, a leading acronym, a CSS measurement.
 */
const NOT_A_SENTENCE =
  /^(?:[A-Z][a-z]+(?:\s[A-Z][a-z]+)*\s?[-/]\s?|[A-Z]{2,}\s|.*\b(?:px|rem|vh|vw|deg)\b)/;

export interface Offence {
  line: number;
  what: string;
}

/** A message the catalog holds: its dotted key, and its text. */
type Entry = [key: string, message: string];

/** A file the sweep reads: where it came from, and what it says. */
export interface Source {
  path: string;
  text: string;
}

/** Whether a string is something a person reads, rather than a token. */
function isCopy(value: string): boolean {
  const stripped = value.trim();
  if (stripped.length < 2 || !words(stripped).length) return false;
  return !NOT_COPY.test(stripped);
}

function words(value: string): string[] {
  return value.match(WORDS) ?? [];
}

/** Whitespace collapsed, so a node the formatter broke over three lines reads as one. */
function collapse(value: string): string {
  return value.trim().replace(/\s+/g, " ");
}

/**
 * Whether every word in a phrase is a unit or an acronym.
 *
 * The formatter test. `HTTP {status}` and `{bytes} KiB` are machine output with a
 * number in them; `{count} files` is a sentence with a number in it, and the only
 * difference is whether any word in it is a word.
 */
function isFormatter(value: string): boolean {
  const found = words(value);
  return found.length > 0 && found.every((word) => UNITS.has(word) || MACHINE_WORD.test(word));
}

/**
 * Whether a phrase - text with its interpolations taken out - is copy.
 *
 * One test where the regexes had four, and no threshold in it. A single word counts,
 * as it always did for a text node sharing a line with its tags: `<p>Settings</p>` was
 * refused and `<DropdownMenuItem onSelect={() => onEdit(c)}>Settings</…>` was not, and
 * the difference was never policy - it was the brace on the line.
 */
function isPhraseCopy(value: string): boolean {
  const prose = collapse(value.replace(ENTITY, " "));
  if (!isCopy(prose)) return false;
  return !isFormatter(prose);
}

/**
 * Whether two ternary branches are one word and its plural.
 *
 * Narrow on purpose: `dir === "asc" ? "desc" : "asc"` is two tokens, not copy, and
 * only the `s` shapes - `"" : "s"`, `"file" : "files"` - are a plural in disguise.
 */
function isPluralPair(first: string, second: string): boolean {
  if ((first === "" && second === "s") || (first === "s" && second === "")) return true;
  if (!first || !second) return false;
  return second === `${first}s` || first === `${second}s`;
}

/**
 * Lines an `i18n-exempt: why` comment covers: its own, and the one below it.
 *
 * Read off the raw text rather than the comment ranges, because the line below is the
 * point. Prettier moves a trailing comment onto its own line the moment the line it
 * annotates gets long enough, and an exemption that stops working when the code is
 * reformatted is an exemption somebody replaces with a key.
 *
 * Two lines is not enough on its own, and `app/not-found.tsx` is why. Its three
 * exemptions sit above an `<h1>` whose words are on the *third* line, because the
 * opening tag carries four Tailwind classes - so the window covered the tag and missed
 * the copy. The regexes never noticed: a text node on a line of its own matched nothing
 * to begin with (#141). `anchors` is the other half of the answer - an exemption covers
 * the element it opens, however many lines that element's attributes take.
 */
function exemptLines(text: string): Set<number> {
  const exempt = new Set<number>();
  const lines = text.split("\n");
  lines.forEach((line, index) => {
    if (EXEMPT.test(line)) {
      exempt.add(index + 1);
      // Past the rest of the comment, so a reason worth two lines still covers the
      // code underneath it. A reason is required, and a required reason is sometimes
      // a sentence - an exemption that only works while it fits on one line is one
      // that fails silently the moment somebody explains themselves properly.
      let scan = index + 1;
      while (scan < lines.length && /^\s*(?:\/\/|\*|\/\*)/.test(lines[scan] ?? "")) scan += 1;
      exempt.add(scan + 1);
    }
  });
  return exempt;
}

function parse(fileName: string, text: string): ts.SourceFile {
  return ts.createSourceFile(
    fileName,
    text,
    ts.ScriptTarget.Latest,
    true,
    fileName.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS,
  );
}

function lineOf(file: ts.SourceFile, position: number): number {
  return file.getLineAndCharacterOfPosition(position).line + 1;
}

/** Whether anything inside this expression renders an element. */
function rendersAnElement(node: ts.Node): boolean {
  if (ts.isJsxElement(node) || ts.isJsxSelfClosingElement(node) || ts.isJsxFragment(node)) {
    return true;
  }
  return ts.forEachChild(node, rendersAnElement) ?? false;
}

/**
 * Whether an interpolation renders something a person sees.
 *
 * `{" "}` is the space the formatter could not leave in the source, not a value: it
 * carries neither a letter nor a digit. Without that, `{" "} to <span>{email}</span>`
 * reads as a count and the word `to` is reported against a line nobody wrote copy on.
 */
function holdsAValue(node: ts.Expression): boolean {
  return /[A-Za-z0-9]/.test(node.getText());
}

/** Whether a node sits inside a call whose string arguments are Tailwind classes. */
function inAClassCall(node: ts.Node): boolean {
  for (let scan: ts.Node | undefined = node.parent; scan; scan = scan.parent) {
    if (ts.isCallExpression(scan)) {
      const called = scan.expression;
      const name = ts.isIdentifier(called)
        ? called.text
        : ts.isPropertyAccessExpression(called)
          ? called.name.text
          : "";
      if (CLASS_CALLS.includes(name)) return true;
    }
  }
  return false;
}

function attributeName(attribute: ts.JsxAttribute): string {
  return ts.isIdentifier(attribute.name) ? attribute.name.text : attribute.name.getText();
}

/** The attribute a literal is the value of, if it is one. */
function owningAttribute(node: ts.Node): ts.JsxAttribute | undefined {
  const parent = node.parent;
  if (parent && ts.isJsxAttribute(parent)) return parent;
  if (parent && ts.isJsxExpression(parent) && parent.parent && ts.isJsxAttribute(parent.parent)) {
    return parent.parent;
  }
  return undefined;
}

/** Whether a literal is markup rather than copy by virtue of where it sits. */
function isMarkup(node: ts.StringLiteralLike): boolean {
  const attribute = owningAttribute(node);
  if (attribute && UNREADABLE_ATTRS.includes(attributeName(attribute))) return true;
  if (inAClassCall(node)) return true;
  const parent = node.parent;
  if (!parent) return false;
  // A module specifier, an object key, a property signature name: a string in a
  // position the language reads rather than a person.
  if (ts.isImportDeclaration(parent) || ts.isExportDeclaration(parent)) return true;
  if (ts.isImportTypeNode(parent) || ts.isExternalModuleReference(parent)) return true;
  if (ts.isLiteralTypeNode(parent)) return true;
  return (
    (ts.isPropertyAssignment(parent) ||
      ts.isPropertySignature(parent) ||
      ts.isEnumMember(parent) ||
      ts.isMethodSignature(parent) ||
      ts.isBindingElement(parent)) &&
    parent.name === node
  );
}

/**
 * A template literal's text with each interpolation replaced by one placeholder.
 *
 * The placeholder is what the whitespace rule is measured against, so it has to be a
 * character no source can hold and no regex reads as a word.
 */
const HOLE = "\u0000";

function templateBody(node: ts.TemplateExpression): string {
  return node.head.text + node.templateSpans.map((span) => `${HOLE}${span.literal.text}`).join("");
}

/**
 * Whether a template literal is a sentence rather than an identifier being assembled.
 *
 * **Whitespace, not a word count.** `` `audience${key}Hint` `` builds a catalog key and
 * `` `Remove ${source.name}` `` is copy, and the two-word threshold that separated them
 * put every one-word `aria-label` and toast in the frontend on the wrong side of the
 * line (#395). A space between a word and the interpolation is what makes it prose:
 * nobody assembles an identifier with spaces in it, and no sentence runs its words
 * together.
 */
export function isTemplateCopy(body: string): boolean {
  if (MACHINE_READ.test(body)) return false;
  const kinds = body
    .split(/\s+/)
    .filter(Boolean)
    .map((token) => {
      const hole = token.includes(HOLE);
      const word = /[A-Za-z]{2,}/.test(token);
      return hole && word ? "glued" : hole ? "hole" : word ? "word" : "other";
    });
  const prose = kinds.some((kind, index) => {
    const next = kinds[index + 1];
    return (
      (kind === "word" && (next === "word" || next === "hole")) ||
      (kind === "hole" && next === "word")
    );
  });
  if (!prose) return false;
  return isPhraseCopy(body.split(HOLE).join(" "));
}

/**
 * One run of JSX children: the text and the interpolations between two elements.
 *
 * A phrase, in other words, and the unit every text rule now works in. An element
 * ends one - `Sign in to <em>{t("workspace")}</em>` is the phrase `Sign in to` and
 * whatever `<em>` holds, which is why the remedy is one `t.rich` message rather than a
 * head, a span and a tail. Whitespace and a `{" "}` do not end one; a `{cond && <X/>}`
 * does, because what it renders is an element.
 */
interface Phrase {
  /** Where the words start, for the report. */
  position: number;
  /** The words, with each interpolation reduced to a space. */
  said: string;
  /** The phrase as it is written, for the message. */
  source: string;
  /** Whether anything is interpolated into it. */
  interpolated: boolean;
}

function phrasesIn(element: ts.JsxElement | ts.JsxFragment, file: ts.SourceFile): Phrase[] {
  const found: Phrase[] = [];
  let said: string[] = [];
  let source: string[] = [];
  let position: number | undefined;
  let interpolated = false;

  const flush = (): void => {
    if (position !== undefined) {
      found.push({
        position,
        said: said.join(""),
        source: collapse(source.join("")),
        interpolated,
      });
    }
    said = [];
    source = [];
    position = undefined;
    interpolated = false;
  };

  for (const child of element.children) {
    if (ts.isJsxText(child)) {
      if (child.containsOnlyTriviaWhiteSpaces) {
        said.push(" ");
        source.push(" ");
        continue;
      }
      // `getStart` on a JsxText already skips the newline and indentation the formatter
      // put in front of the words, which is what makes it the line a person would write
      // the exemption above. Adding that offset a second time walked the report onto the
      // *next* line whenever the indentation was deeper than the phrase was long.
      position ??= child.getStart(file);
      said.push(child.text);
      source.push(child.text);
      continue;
    }
    if (ts.isJsxExpression(child)) {
      if (!child.expression) continue;
      if (rendersAnElement(child.expression)) {
        flush();
        continue;
      }
      if (!holdsAValue(child.expression)) continue;
      said.push(" ");
      source.push(child.getText(file));
      interpolated = true;
      continue;
    }
    flush();
  }
  flush();
  return found;
}

/**
 * Every line an exemption could reasonably be written on to cover this offence.
 *
 * The offence's own line, and the first line of each JSX element, attribute or statement
 * enclosing it. That is what makes `{/* i18n-exempt: why *␀/}` mean "the element below",
 * rather than "the next two lines" - an opening tag with four Tailwind classes on it
 * takes three lines before the copy starts, and the exemption is written above the tag
 * because that is where a person reads it.
 *
 * Walking up stops at the first enclosing statement: an exemption above a `return` covers
 * the expression it returns, and anything wider than that is a file-level opt-out this
 * guard deliberately does not have.
 */
function anchors(node: ts.Node, file: ts.SourceFile): number[] {
  const lines = [lineOf(file, node.getStart(file))];
  for (let scan: ts.Node | undefined = node.parent; scan; scan = scan.parent) {
    const holds =
      ts.isJsxElement(scan) ||
      ts.isJsxSelfClosingElement(scan) ||
      ts.isJsxFragment(scan) ||
      ts.isJsxAttribute(scan) ||
      ts.isJsxOpeningElement(scan);
    if (holds) lines.push(lineOf(file, scan.getStart(file)));
    if (ts.isStatement(scan)) {
      lines.push(lineOf(file, scan.getStart(file)));
      break;
    }
  }
  return lines;
}

/**
 * Every string a person could read in one file, and where.
 *
 * The sweep is the whole offence half of the guard, and it is one walk: a phrase, a
 * readable attribute, a template literal, a sentence in a string, a hand-rolled
 * plural, a toast. What used to be ten regexes with a threshold each is ten node
 * kinds with none, because the parser has already answered the question every
 * threshold was standing in for.
 */
export function offences(fileName: string, text: string): Offence[] {
  const file = parse(fileName, text);
  const exempt = exemptLines(text);
  const found: Offence[] = [];

  const report = (node: ts.Node, position: number, what: string): void => {
    const line = lineOf(file, position);
    if (anchors(node, file).some((anchor) => exempt.has(anchor))) return;
    if (!exempt.has(line)) found.push({ line, what });
  };

  const readString = (node: ts.StringLiteralLike): void => {
    if (isMarkup(node)) return;
    const value = node.text;
    if (!isCopy(value)) return;
    const sentence = /^[A-Z][^\n]*\s/.test(value) && !NOT_A_SENTENCE.test(value);
    const numbered = /^\d+\s+[A-Za-z]/.test(value);
    if (sentence || numbered) report(node, node.getStart(file), `string ${quote(value)}`);
  };

  const visit = (node: ts.Node): void => {
    if (ts.isJsxElement(node) || ts.isJsxFragment(node)) {
      for (const phrase of phrasesIn(node, file)) {
        if (isPhraseCopy(phrase.said)) {
          report(node, phrase.position, `text ${quote(phrase.source)}`);
        }
      }
    }
    if (ts.isJsxAttribute(node) && READABLE_ATTRS.includes(attributeName(node))) {
      const value = node.initializer;
      if (value && ts.isStringLiteral(value) && isCopy(value.text)) {
        report(node, value.getStart(file), `${attributeName(node)}="${value.text}"`);
      }
    }
    if (ts.isTemplateExpression(node) && !inAClassCall(node)) {
      const attribute = owningAttribute(node);
      const markup = attribute !== undefined && UNREADABLE_ATTRS.includes(attributeName(attribute));
      if (!markup && isTemplateCopy(templateBody(node))) {
        report(node, node.getStart(file), `template ${quote(node.getText(file))}`);
      }
    }
    if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) {
      readString(node);
    }
    if (ts.isConditionalExpression(node)) {
      const { whenTrue, whenFalse } = node;
      if (
        ts.isStringLiteral(whenTrue) &&
        ts.isStringLiteral(whenFalse) &&
        isPluralPair(whenTrue.text, whenFalse.text)
      ) {
        report(node, whenTrue.getStart(file), `plural ${quote(node.getText(file))}`);
      }
    }
    if (isToastCall(node)) {
      const argument = node.arguments[0];
      if (argument && ts.isStringLiteralLike(argument) && isCopy(argument.text)) {
        report(node, argument.getStart(file), `toast ${quote(argument.text)}`);
      }
    }
    ts.forEachChild(node, visit);
  };

  visit(file);
  return found.sort((left, right) => left.line - right.line || left.what.localeCompare(right.what));
}

function isToastCall(node: ts.Node): node is ts.CallExpression {
  if (!ts.isCallExpression(node)) return false;
  const called = node.expression;
  return (
    ts.isPropertyAccessExpression(called) &&
    ts.isIdentifier(called.expression) &&
    called.expression.text === "toast" &&
    TOAST_METHODS.includes(called.name.text)
  );
}

/** A literal part of a key template, safe to put in a pattern. */
function escaped(part: string): string {
  return part.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * A value in the report, quoted the way the Python guard quoted it.
 *
 * Backslashes before quotes, and in that order: escaping the quote alone leaves
 * `\'` reading as an escaped backslash followed by the terminator, so a report line
 * about a string holding one is ambiguous about where it ends.
 */
function quote(value: string): string {
  const said = collapse(value);
  const shown = said.length > 120 ? `${said.slice(0, 117)}…` : said;
  return `'${shown.replace(/\\/g, "\\\\").replace(/'/g, "\\'")}'`;
}

/**
 * What binds a translator to a namespace, and every key it names.
 *
 * The *name* matters because it is not always `t` - `tc`, `ts` and `tAgents` are all in
 * this tree, and a rule reading only `t(` would call every key those three name dead.
 * Namespaces are unioned across the file rather than tracked per binding: one file
 * holds up to seven components with a `t` each, and over-reading is the safe direction
 * - it reports fewer dead keys, never a live one.
 */
interface Reads {
  /** Namespaces every translator in the file is bound to. */
  namespaces: Set<string>;
  /** Keys named outright, with the file's namespaces already applied. */
  named: Set<string>;
  /** Key names a `` t(`${x}Label`) `` call could build. */
  built: RegExp[];
  /** Key names read as a literal, with the line each was read on. */
  calls: { key: string; line: number }[];
}

const TRANSLATOR_FACTORIES = ["useTranslations", "getTranslations"];
const TRANSLATOR_METHODS = ["rich", "markup", "has"];

function translatorFactory(node: ts.Expression): ts.CallExpression | undefined {
  const call = ts.isAwaitExpression(node) ? node.expression : node;
  if (!ts.isCallExpression(call)) return undefined;
  const called = call.expression;
  const name = ts.isIdentifier(called)
    ? called.text
    : ts.isPropertyAccessExpression(called)
      ? called.name.text
      : "";
  return TRANSLATOR_FACTORIES.includes(name) ? call : undefined;
}

function keyReads(fileName: string, text: string): Reads {
  const file = parse(fileName, text);
  const namespaces = new Set<string>();
  const bound = new Set<string>();

  const bindings = (node: ts.Node): void => {
    if (ts.isVariableDeclaration(node) && node.initializer && ts.isIdentifier(node.name)) {
      const factory = translatorFactory(node.initializer);
      if (factory) {
        bound.add(node.name.text);
        const argument = factory.arguments[0];
        namespaces.add(argument && ts.isStringLiteralLike(argument) ? argument.text : "");
      }
    }
    ts.forEachChild(node, bindings);
  };
  bindings(file);

  const named = new Set<string>();
  const built: RegExp[] = [];
  const calls: { key: string; line: number }[] = [];
  const dotted = (key: string): string[] =>
    [...namespaces].map((namespace) => (namespace ? `${namespace}.${key}` : key));

  const reads = (node: ts.Node): void => {
    if (ts.isCallExpression(node)) {
      const called = node.expression;
      const name = ts.isIdentifier(called)
        ? called.text
        : ts.isPropertyAccessExpression(called) &&
            ts.isIdentifier(called.expression) &&
            TRANSLATOR_METHODS.includes(called.name.text)
          ? called.expression.text
          : "";
      const argument = node.arguments[0];
      if (bound.has(name) && argument) {
        if (ts.isStringLiteralLike(argument)) {
          for (const key of dotted(argument.text)) named.add(key);
          calls.push({ key: argument.text, line: lineOf(file, argument.getStart(file)) });
        } else if (ts.isTemplateExpression(argument)) {
          for (const key of dotted(templateBody(argument))) {
            built.push(new RegExp(`^${key.split(HOLE).map(escaped).join("\\w*")}$`));
          }
        }
      }
    }
    ts.forEachChild(node, reads);
  };
  if (bound.size) reads(file);

  return { namespaces, named, built, calls };
}

/**
 * Keys a file reads that the catalog does not hold.
 *
 * The other half of the rule. The offence sweep catches copy that never made it *out*
 * of a component; this catches a key that never made it *in* - a rename, a typo, or a
 * file whose translator is scoped to one namespace while its keys were filed under
 * another, which renders the key itself on screen and reports an error nobody sees
 * until a person opens that page.
 */
export function missingKeys(fileName: string, text: string, catalog: unknown): Offence[] {
  const { namespaces, calls } = keyReads(fileName, text);
  const scoped = [...namespaces].filter(Boolean);
  if (!scoped.length) return [];
  return calls
    .filter(({ key }) => !scoped.some((namespace) => holds(catalog, `${namespace}.${key}`)))
    .map(({ key, line }) => ({ line, what: `${key} (in ${scoped.join(", ")})` }));
}

/** Every spelling of `key` a module-level table could hold, whole key first. */
function namespaceRelative(key: string): string[] {
  const parts = key.split(".");
  return parts.map((_, index) => parts.slice(index).join("."));
}

/** A string that could be the name of a key, whole. */
const KEY_SHAPED = /^[A-Za-z][\w-]*(?:\.[A-Za-z][\w-]*)*$/;

/**
 * Catalog keys nothing in the frontend reads.
 *
 * `missingKeys` run the other way round, and it catches what neither that sweep nor
 * the offence sweep can: the extraction pass that produced this catalog sometimes
 * lifted a string into a key and left the component reading the literal beside it.
 * Both halves then look clean - the key is valid, and a line no rule reads is a line
 * nothing is reported about - while the English stays on screen under every locale.
 * `Continue` on the sync wizard and `(inactive)` in the bot picker shipped that way
 * (#425).
 *
 * A key counts as read when a translator names it, when a `` t(`…`) `` pattern could
 * build it, or when any namespace-relative spelling of it appears as a plain string
 * anywhere in the frontend - the last because a table of keys is read back through
 * `t(item.labelKey)`, and following the table to the call is a data-flow question a
 * syntax tree does not answer either. That third clause is loose on purpose: it is
 * what makes the rule safe to fail a build on, and it is also the ceiling on what the
 * rule can find.
 */
export function unreadKeys(catalog: unknown, sources: Source[]): string[] {
  const named = new Set<string>();
  const built: RegExp[] = [];
  const spelled = new Set<string>();
  for (const { path, text } of sources) {
    const reads = keyReads(path, text);
    for (const key of reads.named) named.add(key);
    built.push(...reads.built);
    for (const literal of literalsIn(path, text)) {
      if (KEY_SHAPED.test(literal.text)) spelled.add(literal.text);
    }
  }
  return [...catalogKeys(catalog)]
    .filter(
      (key) =>
        !named.has(key) &&
        !namespaceRelative(key).some((spelling) => spelled.has(spelling)) &&
        !built.some((pattern) => pattern.test(key)),
    )
    .sort();
}

/** Every string literal in one file, and the line it sits on. */
function literalsIn(fileName: string, text: string): { text: string; line: number }[] {
  const file = parse(fileName, text);
  const found: { text: string; line: number }[] = [];
  const visit = (node: ts.Node): void => {
    if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) {
      found.push({ text: node.text, line: lineOf(file, node.getStart(file)) });
    }
    ts.forEachChild(node, visit);
  };
  visit(file);
  return found;
}

/**
 * Catalog messages whose words are also sitting in the frontend, written out.
 *
 * The signature of #425, and the half `unreadKeys` cannot see on its own: a key read
 * *somewhere* while another component spells the same sentence out. It is also the
 * rule that reaches a `.ts` file, which the offence sweep still does not - every
 * `toast.success("Member removed")` in `src/hooks/**` had been invisible to it since
 * the guard was written.
 *
 * Anchored on the catalog rather than on the source, which is what keeps it cheap:
 * the sentence is already known, so the question is only where the words are. A run
 * is a JSX phrase or a whole string literal, compared whole - a substring search was
 * the first shape of this rule and it reported `Failed to load` inside `Failed to
 * load conversations` eleven times. Skipped: a message holding an ICU argument or a
 * tag, which no run can equal verbatim, and anything under two words, where a match
 * says nothing.
 */
export function duplicatedInSource(
  catalog: unknown,
  sources: Source[],
): { path: string; line: number; key: string; words: string }[] {
  const wanted = new Map<string, string>();
  for (const [key, message] of catalogEntries(catalog)) {
    if (isCopy(message) && !/[{}<>]/.test(message) && message.split(/\s+/).length >= 2) {
      wanted.set(message, key);
    }
  }
  const found: { path: string; line: number; key: string; words: string }[] = [];
  for (const { path, text } of sources) {
    const exempt = exemptLines(text);
    for (const run of runsIn(path, text)) {
      const key = wanted.get(collapse(run.text));
      if (key !== undefined && !exempt.has(run.line)) {
        found.push({ path, line: run.line, key, words: collapse(run.text) });
      }
    }
  }
  return found.sort((left, right) => left.path.localeCompare(right.path) || left.line - right.line);
}

/**
 * Every run of prose in a file: a JSX phrase, or a whole string literal.
 *
 * `Sign in to <em>{t("yourWorkspace")}</em>` is the run `Sign in to` and the run
 * `yourWorkspace`, either of which can be compared against a whole message. Five
 * `auth` headings shipped in English as exactly that shape, none of them inside
 * quotes.
 */
function runsIn(fileName: string, text: string): { text: string; line: number }[] {
  const file = parse(fileName, text);
  const found: { text: string; line: number }[] = [];
  const visit = (node: ts.Node): void => {
    if (ts.isJsxElement(node) || ts.isJsxFragment(node)) {
      for (const phrase of phrasesIn(node, file)) {
        if (!phrase.interpolated) {
          found.push({ text: phrase.said, line: lineOf(file, phrase.position) });
        }
      }
    }
    if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) {
      found.push({ text: node.text, line: lineOf(file, node.getStart(file)) });
    }
    ts.forEachChild(node, visit);
  };
  visit(file);
  return found;
}

/**
 * Every message the catalog holds: its dotted key, and its text.
 *
 * `en.json` is a tree of namespaces whose leaves are messages, so anything that is not
 * an object is one. The throw is what says so out loud - a number or a list in there
 * would otherwise be compared against source as `String(value)` and quietly match
 * nothing.
 */
function catalogEntries(node: unknown, prefix = ""): Entry[] {
  if (typeof node === "object" && node !== null && !Array.isArray(node)) {
    return Object.entries(node).flatMap(([key, value]) =>
      catalogEntries(value, `${prefix}${key}.`),
    );
  }
  const key = prefix.replace(/\.$/, "");
  if (typeof node !== "string") throw new Error(`${key} is not a message`);
  return [[key, node]];
}

function catalogKeys(node: unknown): Set<string> {
  return new Set(catalogEntries(node).map(([key]) => key));
}

function holds(catalog: unknown, dotted: string): boolean {
  let node: unknown = catalog;
  for (const part of dotted.split(".")) {
    if (typeof node !== "object" || node === null || !(part in node)) return false;
    node = (node as Record<string, unknown>)[part];
  }
  return typeof node === "string";
}

function sourceFiles(directory: string): string[] {
  const found: string[] = [];
  for (const entry of readdirSync(directory).sort()) {
    const path = join(directory, entry);
    if (statSync(path).isDirectory()) {
      found.push(...sourceFiles(path));
      continue;
    }
    const readable = /\.tsx?$/.test(entry) && !SKIPPED_NAMES.some((name) => entry.endsWith(name));
    if (readable) found.push(path);
  }
  return found;
}

/**
 * A failing report, capped unless `--all`.
 *
 * A build failure nobody scrolls to the end of is a build failure nobody reads, and
 * somebody working through a backlog needs the whole of it.
 */
function print(headline: string, lines: string[], all: boolean, remedy?: string): void {
  const shown = all ? lines : lines.slice(0, 200);
  console.log(`${lines.length} ${headline}\n`);
  for (const line of shown) console.log(`  ${line}`);
  if (lines.length > shown.length) {
    console.log(`  … and ${lines.length - shown.length} more (--all to list them)`);
  }
  if (remedy) console.log(`\n${remedy}`);
}

function main(argv: string[]): number {
  const all = argv.includes("--all");
  const catalog: unknown = JSON.parse(readFileSync(CATALOG, "utf8"));

  // Three file sets, and the difference between them is what each rule can honestly
  // say. `sources` is everything: the catalog rules read a `.ts` file because a
  // hook's toast is copy, and read the `dev/` playground because a key it reads is
  // not dead. `product` drops the playground, whose copy is nobody's to translate.
  // `sweep` is `.tsx` alone - the offence rules are JSX rules, and the 406 offences a
  // `.ts` file holds are #446 rather than part of this. Tests are out of all three: a
  // test names its copy.
  const sources: Source[] = sourceFiles(SRC).map((path) => ({
    path,
    text: readFileSync(path, "utf8"),
  }));
  const product = sources.filter(({ path }) => !SKIPPED_DIRS.some((dir) => path.includes(dir)));
  const sweep = product.filter(({ path }) => path.endsWith(".tsx"));

  const failures: string[] = [];
  const absent: string[] = [];
  for (const { path, text } of sweep) {
    const shown = relative(ROOT, path);
    for (const { line, what } of offences(path, text)) failures.push(`${shown}:${line}: ${what}`);
    for (const { line, what } of missingKeys(path, text, catalog)) {
      absent.push(`${shown}:${line}: ${what}`);
    }
  }

  if (failures.length) {
    print(
      "hardcoded string(s). Every one belongs in messages/en.json:",
      failures,
      all,
      "Move the string into the catalog and read it with useTranslations, or mark a\n" +
        "genuine non-string with `i18n-exempt: <reason>` on the line or the one above.",
    );
    return 1;
  }

  if (absent.length) {
    print("message(s) read but not in messages/en.json:", absent, all);
    return 1;
  }

  const unread = unreadKeys(catalog, sources);
  if (unread.length) {
    print(
      "message(s) in messages/en.json that nothing reads:",
      unread,
      all,
      "Delete the key, or read it. A key nothing reads is a key a translator\n" +
        "translates for nobody - and where a component kept the literal beside it,\n" +
        "the English is still on screen in every locale.",
    );
    return 1;
  }

  const duplicated = duplicatedInSource(catalog, product);
  if (duplicated.length) {
    print(
      "message(s) also written out in the source:",
      duplicated.map(
        ({ path, line, key, words }) => `${relative(ROOT, path)}:${line}: ${key} = '${words}'`,
      ),
      all,
      "Read the key that already holds this sentence.",
    );
    return 1;
  }

  console.log(
    `No hardcoded copy in frontend/src. ${catalogKeys(catalog).size} messages in en.json.`,
  );
  return 0;
}

const entry = process.argv[1];
if (entry !== undefined && import.meta.url === pathToFileURL(entry).href) {
  process.exit(main(process.argv.slice(2)));
}
