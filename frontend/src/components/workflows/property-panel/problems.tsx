"use client";

import { useState } from "react";
import { AlertTriangle, ChevronDown, ChevronRight } from "lucide-react";
import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui";
import type { ValidationProblem } from "@/components/workflows/validation";
import {
  nodeDisplayName,
  type NodeCatalog,
  type Uuid,
  type WorkflowGraph,
} from "@/lib/workflows/types";

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

/**
 * Every node's name as the editor shows it: its step's name, with a short id only
 * where two steps of the graph share that name - the one case a name alone
 * cannot say which step is meant.
 */
export function nodeNames(graph: WorkflowGraph | null, catalog: NodeCatalog): Map<Uuid, string> {
  if (graph === null) return new Map();
  const named = graph.nodes.map((node) => {
    const definition = catalog.items.find(
      (item) => item.id === node.definition_id && item.version === node.definition_version,
    );
    return [node.id, definition?.name ?? node.definition_id] as const;
  });
  const uses = new Map<string, number>();
  for (const [, name] of named) uses.set(name, (uses.get(name) ?? 0) + 1);
  return new Map(
    named.map(([id, name]) => [id, nodeDisplayName(name, id, (uses.get(name) ?? 0) > 1)]),
  );
}

/** A warning badge with a translated, pluralised count, or nothing when a node is clean. */
export function WarningBadge({ count }: { count: number }) {
  const t = useTranslations("workflows");
  if (count === 0) return null;
  return (
    <Badge variant="destructive" aria-label={t("panelWarningCount", { count })}>
      <AlertTriangle className="h-3.5 w-3.5" />
      {count}
    </Badge>
  );
}

/**
 * The collapsible problems list in the panel footer — every client-side problem in
 * the graph, each naming the node it scopes to and linking to it, so a click
 * selects it and brings it into view. Collapsed by default; nothing renders when
 * the graph is clean.
 */
export function ProblemsFooter({
  problems,
  names,
  onSelectNode,
  defaultOpen = false,
}: {
  problems: readonly ValidationProblem[];
  /** Each node's name, from {@link nodeNames}. */
  names: ReadonlyMap<Uuid, string>;
  onSelectNode: (nodeId: Uuid) => void;
  /** Open from the start - where the list is what the panel has to show. */
  defaultOpen?: boolean;
}) {
  const t = useTranslations("workflows");
  const [open, setOpen] = useState(defaultOpen);
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
                  <span>
                    {names.has(problem.nodeId) && (
                      <span className="text-foreground font-medium">
                        {names.get(problem.nodeId)}
                        {problem.field !== null && (
                          <span className="font-mono font-normal"> · {problem.field}</span>
                        )}
                        {": "}
                      </span>
                    )}
                    {problem.message}
                  </span>
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
