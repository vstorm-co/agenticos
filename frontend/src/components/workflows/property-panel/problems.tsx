"use client";

import { useState } from "react";
import { AlertTriangle, ChevronDown, ChevronRight } from "lucide-react";
import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui";
import type { ValidationProblem } from "@/components/workflows/validation";
import type { Uuid } from "@/lib/workflows/types";

/**
 * The field-scoped messages for one node, keyed by `target_field` path — what the
 * form hands each `BindingField` and each scalar leaf for its `error` slot. The
 * first message per field wins, so a field shows one message rather than a stack.
 */
export function fieldErrors(
  problems: readonly ValidationProblem[],
  nodeId: Uuid,
): Map<string, string> {
  const map = new Map<string, string>();
  for (const problem of problems) {
    if (problem.nodeId !== nodeId || problem.field === null) continue;
    if (!map.has(problem.field)) map.set(problem.field, problem.message);
  }
  return map;
}

/** A node's problems that scope to the whole node, not one field — shown above its form. */
export function nodeLevelProblems(
  problems: readonly ValidationProblem[],
  nodeId: Uuid,
): ValidationProblem[] {
  return problems.filter((problem) => problem.nodeId === nodeId && problem.field === null);
}

/** How many problems, of any scope, a node has — the badge count. */
export function nodeProblemCount(problems: readonly ValidationProblem[], nodeId: Uuid): number {
  return problems.filter((problem) => problem.nodeId === nodeId).length;
}

/** A warning badge with a translated, pluralised count, or nothing when a node is clean. */
export function WarningBadge({ count }: { count: number }) {
  const t = useTranslations("workflows");
  if (count === 0) return null;
  return (
    <Badge variant="warning" aria-label={t("panelWarningCount", { count })}>
      <AlertTriangle className="h-3.5 w-3.5" />
      {count}
    </Badge>
  );
}

/**
 * The collapsible problems list in the panel footer — every client-side problem in
 * the graph, each linking to the node it scopes to so a click selects it. Collapsed
 * by default; nothing renders when the graph is clean.
 */
export function ProblemsFooter({
  problems,
  onSelectNode,
}: {
  problems: readonly ValidationProblem[];
  onSelectNode: (nodeId: Uuid) => void;
}) {
  const t = useTranslations("workflows");
  const [open, setOpen] = useState(false);
  if (problems.length === 0) return null;

  return (
    <div className="border-border/60 border-t pt-3">
      <button
        type="button"
        className="text-muted-foreground flex w-full items-center gap-1.5 text-xs font-medium"
        aria-expanded={open}
        onClick={() => setOpen((shown) => !shown)}
      >
        {open ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
        {t("panelProblemsCount", { count: problems.length })}
      </button>
      {open && (
        <ul className="mt-2 space-y-1.5">
          {problems.map((problem, index) => (
            <li key={index} className="text-xs">
              {problem.nodeId === null ? (
                <span className="text-muted-foreground flex items-start gap-1.5">
                  <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                  {problem.message}
                </span>
              ) : (
                <button
                  type="button"
                  className="hover:text-foreground text-muted-foreground flex items-start gap-1.5 text-left"
                  onClick={() => onSelectNode(problem.nodeId as Uuid)}
                >
                  <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                  {problem.message}
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
