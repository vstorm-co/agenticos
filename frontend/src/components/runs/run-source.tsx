"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui";
import { ROUTES } from "@/lib/constants";
import type { AgentRun } from "@/types/runs";

type Context = { href: string; label: string };

/** Where the work a run did is read: its eval run, Improve session, gap topic or dataset. */
function context(run: AgentRun): Context | null {
  const origin = run.origin;
  if (run.eval_case) {
    return {
      href: `${ROUTES.AGENTS}/${run.eval_case.agent_id}/evals/${run.eval_case.eval_run_id}`,
      label: "openEvalRun",
    };
  }
  if (!origin) return null;
  if (origin.agent_id) {
    return origin.improvement_id
      ? {
          href: `${ROUTES.AGENTS}/${origin.agent_id}/improve/${origin.improvement_id}`,
          label: "openSession",
        }
      : { href: `${ROUTES.AGENTS}/${origin.agent_id}`, label: "openAgent" };
  }
  if (origin.knowledge_base_id) {
    const gaps = `${ROUTES.RAG}/${origin.knowledge_base_id}?tab=gaps`;
    return origin.topic_id
      ? { href: `${gaps}&topic=${origin.topic_id}`, label: "openTopic" }
      : { href: gaps, label: "openGaps" };
  }
  if (origin.dataset_id) {
    return { href: `${ROUTES.DATASETS}/${origin.dataset_id}?tab=generated`, label: "openDataset" };
  }
  return null;
}

/**
 * What an evaluation or platform-agent row is, beside the surface it ran on:
 * Improve, Eval, Grader, Test questions or Knowledge gaps, and a link to where
 * that work is read. Nothing for a conversation.
 */
export function RunSourceTag({ run }: { run: AgentRun }) {
  const t = useTranslations("pages.runs.source");
  if (!run.origin && run.surface !== "eval") return null;
  const where = context(run);
  return (
    <span className="flex items-center gap-1.5 text-xs whitespace-nowrap">
      <Badge variant="outline" title={run.origin?.agent_name}>
        {t(`kind.${run.origin?.kind ?? "eval"}`)}
      </Badge>
      {where && (
        <Link
          href={where.href}
          className="underline underline-offset-4"
          // The link leaves the page; the row underneath opens the run detail.
          onClick={(event) => event.stopPropagation()}
        >
          {t(`open.${where.label}`)}
        </Link>
      )}
    </span>
  );
}
