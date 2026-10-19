"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui";
import { ROUTES } from "@/lib/constants";
import { describeCheck } from "@/lib/scoring";
import type { CaseScore } from "@/types/scoring";

type Expected = Pick<
  CaseScore,
  | "dataset_id"
  | "case_id"
  | "question"
  | "case_tags"
  | "reference_answer"
  | "expected_tool_calls"
  | "order_mode"
  | "checks"
>;

/**
 * What the scored revision of the case asked and expected: the question - a link
 * opening the case - with its tags, the reference answer, the tool calls in
 * their order mode, and the checks.
 */
export function ScoreExpectation({ score }: { score: Expected }) {
  const t = useTranslations("datasets.scoring");
  return (
    <dl className="bg-muted/40 space-y-2 rounded-md px-3 py-2 text-sm">
      <div>
        <dt className="text-muted-foreground text-xs">{t("question")}</dt>
        <dd className="space-y-1">
          <Link
            href={`${ROUTES.DATASET_DETAIL(score.dataset_id)}?tab=cases&case=${score.case_id}`}
            className="block font-medium break-words whitespace-pre-wrap hover:underline"
          >
            {score.question}
          </Link>
          {score.case_tags.length > 0 && (
            <span className="flex flex-wrap gap-1">
              {score.case_tags.map((tag) => (
                <Badge key={tag} variant="outline" className="font-normal">
                  {tag}
                </Badge>
              ))}
            </span>
          )}
        </dd>
      </div>
      {score.reference_answer && (
        <div>
          <dt className="text-muted-foreground text-xs">{t("referenceAnswer")}</dt>
          <dd className="break-words whitespace-pre-wrap">{score.reference_answer}</dd>
        </div>
      )}
      {score.expected_tool_calls.length > 0 && (
        <div>
          <dt className="text-muted-foreground text-xs">
            {t("expectedCallsIn", { order: score.order_mode })}
          </dt>
          <dd>
            <ul className="font-mono text-xs">
              {score.expected_tool_calls.map((call, index) => (
                <li key={`${call.tool}:${index}`} className="break-all">
                  {call.tool}
                  {Object.keys(call.args).length > 0 && ` ${JSON.stringify(call.args)}`}
                </li>
              ))}
            </ul>
          </dd>
        </div>
      )}
      {score.checks.length > 0 && (
        <div>
          <dt className="text-muted-foreground text-xs">{t("scorer.check")}</dt>
          <dd>
            <ul className="font-mono text-xs">
              {score.checks.map((check, index) => (
                <li key={`${check.type}:${index}`} className="break-all">
                  {describeCheck(check)}
                </li>
              ))}
            </ul>
          </dd>
        </div>
      )}
    </dl>
  );
}
