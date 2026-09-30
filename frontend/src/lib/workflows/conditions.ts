/**
 * A condition built from rows - "score is at least 50", "name contains Ada" -
 * written as the JMESPath expression Filter, If and Switch evaluate, and read
 * back from one.
 *
 * Only the expressions this module writes are read back: anything else - one
 * typed by hand, one this builder cannot show - reads as null, and the field
 * shows it as the expression it is. So a condition never changes meaning by
 * being opened.
 *
 * `root` is what the expression reads: `item` for Filter, which looks at each
 * item of a list, `value` for If and Switch. An empty field is the root itself -
 * a list of names, filtered on `item == 'Ada'`.
 */

export type ConditionOp =
  | "eq"
  | "ne"
  | "gt"
  | "gte"
  | "lt"
  | "lte"
  | "contains"
  | "startsWith"
  | "endsWith"
  | "notEmpty"
  | "empty";

export interface ConditionRow {
  /** A path into the root, dot-separated: `score`, `address.city`. */
  field: string;
  op: ConditionOp;
  /** What the field is compared with, as typed; unused by the two emptiness checks. */
  value: string;
}

export type ConditionJoin = "and" | "or";

export interface Condition {
  rows: ConditionRow[];
  join: ConditionJoin;
}

export const CONDITION_OPS: readonly ConditionOp[] = [
  "eq",
  "ne",
  "gt",
  "gte",
  "lt",
  "lte",
  "contains",
  "startsWith",
  "endsWith",
  "notEmpty",
  "empty",
];

/** The operators that compare with nothing. */
export function takesNoValue(op: ConditionOp): boolean {
  return op === "notEmpty" || op === "empty";
}

const COMPARE: Partial<Record<ConditionOp, string>> = {
  eq: "==",
  ne: "!=",
  gt: ">",
  gte: ">=",
  lt: "<",
  lte: "<=",
};
const TEXT_FUNCTION: Partial<Record<ConditionOp, string>> = {
  startsWith: "starts_with",
  endsWith: "ends_with",
};

const IDENTIFIER = /^[A-Za-z_][A-Za-z0-9_]*$/;
const NUMBER = /^-?\d+(\.\d+)?$/;

function pathOf(root: string, field: string): string {
  const segments = field
    .split(".")
    .map((segment) => segment.trim())
    .filter((segment) => segment !== "");
  return [root, ...segments.map((s) => (IDENTIFIER.test(s) ? s : JSON.stringify(s)))].join(".");
}

function text(value: string): string {
  return `'${value.replace(/\\/g, "\\\\").replace(/'/g, "\\'")}'`;
}

/** A number or a yes/no is compared as one; anything else as text. */
function literal(value: string): string {
  const trimmed = value.trim();
  return NUMBER.test(trimmed) || trimmed === "true" || trimmed === "false"
    ? `\`${trimmed}\``
    : text(value);
}

function clause(root: string, row: ConditionRow): string {
  const path = pathOf(root, row.field);
  const symbol = COMPARE[row.op];
  if (symbol !== undefined) return `${path} ${symbol} ${literal(row.value)}`;
  const fn = TEXT_FUNCTION[row.op];
  // `|| ''` so a missing field is no match rather than a failed step.
  if (fn !== undefined) return `${fn}(to_string(${path} || ''), ${text(row.value)})`;
  if (row.op === "contains") return `contains(${path} || '', ${text(row.value)})`;
  return row.op === "empty" ? `!${path}` : path;
}

/** Whether a row says enough to be written: a value, unless its check takes none. */
export function isComplete(row: ConditionRow): boolean {
  return takesNoValue(row.op) || row.value.trim() !== "";
}

/** The expression the rows make, or "" when none of them is complete yet. */
export function compileCondition(condition: Condition, root: string): string {
  return condition.rows
    .filter(isComplete)
    .map((row) => clause(root, row))
    .join(condition.join === "and" ? " && " : " || ");
}

/** The expression cut at its top-level `&&` or `||`, outside any quotes or parentheses. */
function split(expression: string): { parts: string[]; join: ConditionJoin } | null {
  const parts: string[] = [];
  const joins = new Set<ConditionJoin>();
  let quote: string | null = null;
  let depth = 0;
  let start = 0;
  for (let i = 0; i < expression.length; i += 1) {
    const char = expression[i] as string;
    if (quote !== null) {
      if (char === "\\") i += 1;
      else if (char === quote) quote = null;
      continue;
    }
    if (char === "'" || char === "`" || char === '"') {
      quote = char;
      continue;
    }
    if (char === "(") depth += 1;
    if (char === ")") depth -= 1;
    const pair = expression.slice(i, i + 4);
    if (depth === 0 && (pair === " && " || pair === " || ")) {
      joins.add(pair === " && " ? "and" : "or");
      parts.push(expression.slice(start, i));
      start = i + 4;
      i += 3;
    }
  }
  parts.push(expression.slice(start));
  if (joins.size > 1) return null;
  return { parts, join: [...joins][0] ?? "and" };
}

const SEGMENT = String.raw`(?:[A-Za-z_][A-Za-z0-9_]*|"(?:[^"\\]|\\.)*")`;
const TEXT = String.raw`'((?:[^'\\]|\\.)*)'`;
const LITERAL = String.raw`(?:${TEXT}|\x60([^\x60]*)\x60)`;

function fieldOf(path: string): string {
  return (path.match(new RegExp(SEGMENT, "g")) ?? [])
    .map((segment) => (segment.startsWith('"') ? (JSON.parse(segment) as string) : segment))
    .join(".");
}

function unescape(value: string): string {
  return value.replace(/\\(.)/g, "$1");
}

function parseClause(part: string, root: string): ConditionRow | null {
  const path = String.raw`${root}((?:\.${SEGMENT})*)`;
  // The path group always matches, if only the empty string: the root itself.
  const strip = (raw: string | undefined) => fieldOf((raw as string).slice(1));
  const patterns: [RegExp, (match: RegExpExecArray) => ConditionRow | null][] = [
    [
      new RegExp(String.raw`^contains\(${path} \|\| '', ${TEXT}\)$`),
      (m) => ({ field: strip(m[1]), op: "contains", value: unescape(m[2] as string) }),
    ],
    [
      new RegExp(String.raw`^(starts_with|ends_with)\(to_string\(${path} \|\| ''\), ${TEXT}\)$`),
      (m) => ({
        field: strip(m[2]),
        op: m[1] === "starts_with" ? "startsWith" : "endsWith",
        value: unescape(m[3] as string),
      }),
    ],
    [new RegExp(String.raw`^!${path}$`), (m) => ({ field: strip(m[1]), op: "empty", value: "" })],
    [
      new RegExp(String.raw`^${path} (==|!=|>=|<=|>|<) ${LITERAL}$`),
      (m) => {
        const op = (Object.keys(COMPARE) as ConditionOp[]).find((key) => COMPARE[key] === m[2]);
        const typed = m[4];
        if (typed !== undefined && !NUMBER.test(typed) && typed !== "true" && typed !== "false") {
          return null;
        }
        return {
          field: strip(m[1]),
          op: op as ConditionOp,
          value: typed ?? unescape(m[3] as string),
        };
      },
    ],
    [new RegExp(String.raw`^${path}$`), (m) => ({ field: strip(m[1]), op: "notEmpty", value: "" })],
  ];
  for (const [pattern, read] of patterns) {
    const match = pattern.exec(part);
    if (match !== null) return read(match);
  }
  return null;
}

/**
 * The rows an expression is, when this module could have written it - or null,
 * and the expression is shown as it is.
 */
export function parseCondition(expression: string, root: string): Condition | null {
  const cut = split(expression.trim());
  if (cut === null) return null;
  const rows: ConditionRow[] = [];
  for (const part of cut.parts) {
    const row = parseClause(part, root);
    if (row === null) return null;
    rows.push(row);
  }
  const condition = { rows, join: cut.join };
  // Read back only what writes back the same: nothing changes by being opened.
  return compileCondition(condition, root) === expression.trim() ? condition : null;
}
