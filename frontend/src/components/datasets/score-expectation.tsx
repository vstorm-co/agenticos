"use client";

import { useState } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";

import { MarkdownContent } from "@/components/chat/markdown-content";
import { Badge, Button } from "@/components/ui";
import { cn } from "@/lib/utils";
import { ROUTES } from "@/lib/constants";
import { describeCheck } from "@/lib/scoring";
import type { CaseScore } from "@/types/scoring";

type Expected = Pick<
  CaseScore,
  | "dataset_id"
  | "case_id"
  | "case_masked"
  | "question"
  | "case_tags"
  | "reference_answer"
  | "expected_tool_calls"
  | "order_mode"
  | "checks"
>;

/** Keep a long reference close enough to the actual answer to compare them. */
function ReferenceAnswer({ answer }: { answer: string }) {
  const t = useTranslations("datasets.scoring");
  const [open, setOpen] = useState(false);
  const long = answer.length > 240;
  return (
    <div className="space-y-2">
      <div
        className={cn(
          "prose-sm min-w-0 leading-relaxed wrap-anywhere",
          long && !open && "line-clamp-3",
        )}
      >
        <MarkdownContent content={answer} inertImages />
      </div>
      {long && (
        <Button
          variant="link"
          size="sm"
          className="h-auto px-0"
          aria-expanded={open}
          onClick={() => setOpen((value) => !value)}
        >
          {open ? t("showLess") : t("showAll")}
        </Button>
      )}
    </div>
  );
}

/**
 * What the scored revision of the case asked and expected: the question - a link
 * opening the case - with its tags, the reference answer, the tool calls in
 * their order mode, and the checks.
 */
export function ScoreExpectation({ score }: { score: Expected }) {
  const t = useTranslations("datasets.scoring");
  return (
    <dl className="bg-muted/20 min-w-0 space-y-4 rounded-lg border p-4 text-sm">
      <div>
        <dt className="text-muted-foreground text-xs">{t("question")}</dt>
        <dd className="space-y-1">
          <Link
            href={`${ROUTES.DATASET_DETAIL(score.dataset_id)}?tab=cases&case=${score.case_id}`}
            className="block font-medium break-words whitespace-pre-wrap hover:underline"
          >
            {score.case_masked ? t("maskedConversation") : score.question}
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
          <dd className="prose-sm mt-2 min-w-0 leading-relaxed wrap-anywhere">
            <ReferenceAnswer key={score.reference_answer} answer={score.reference_answer} />
          </dd>
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
