"use client";

import { useLocale, useTranslations } from "next-intl";

import { describeCheck } from "@/lib/scoring";
import type { CaseCheck } from "@/types/datasets";
import { seconds, usd } from "./format";

const INLINE_IGNORE_CASE = "(?i)";
const PATTERN_SYNTAX = /[.^$*+?()[\]{}|\\]/;

type TextRule = { key: "contains" | "not_contains" | "equals" | "pattern"; value: string };

/**
 * A text check as the rule a person would say. A pattern that is only a word,
 * optionally behind `(?i)`, is read as mentioning that word; any other pattern
 * is quoted as written.
 */
function textRule(type: string, value: string): TextRule {
  if (type !== "regex") return { key: type as TextRule["key"], value };
  const bare = value.startsWith(INLINE_IGNORE_CASE)
    ? value.slice(INLINE_IGNORE_CASE.length)
    : value;
  return bare !== "" && !PATTERN_SYNTAX.test(bare)
    ? { key: "contains", value: bare }
    : { key: "pattern", value };
}

/** One check of a case in words, with the check as stored behind it on hover. */
export function CheckSummary({ check }: { check: CaseCheck }) {
  const t = useTranslations("evals.case.expect.check");
  const locale = useLocale();
  const raw = describeCheck(check);
  let rule: string;
  switch (check.type) {
    case "contains":
    case "not_contains":
    case "equals":
    case "regex": {
      const value = String(check.value);
      const { key, value: shown } = textRule(check.type, value);
      // Text checks ignore letter case unless told otherwise, and `(?i)` says so too.
      const exact = check.case_sensitive === true && !value.startsWith(INLINE_IGNORE_CASE);
      const said = t(key, { value: shown, exact: String(exact) });
      rule = typeof check.path === "string" ? t("atPath", { path: check.path, rule: said }) : said;
      break;
    }
    case "max_cost_usd":
      rule = t("maxCost", { amount: usd(String(check.value), locale) });
      break;
    case "max_latency_ms":
      rule = t("maxLatency", { duration: seconds(Number(check.value), locale) });
      break;
    case "json_schema":
      rule = t("jsonSchema");
      break;
    case "judge":
      rule = t("judge", { criterion: String(check.criterion) });
      break;
    default:
      return <code className="break-all">{raw}</code>;
  }
  return <span title={raw}>{rule}</span>;
}
