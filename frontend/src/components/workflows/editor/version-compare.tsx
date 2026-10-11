"use client";

import { useMemo } from "react";
import { useTranslations } from "next-intl";

import { type ChangedField, type StepChange, diffGraphs } from "@/lib/workflows/graph-diff";
import { cn } from "@/lib/utils";
import type { NodeDefinition, WorkflowGraph } from "@/lib/workflows/types";

import { VersionPreview } from "./version-preview";

const ORDER: Record<StepChange, number> = { added: 0, changed: 1, removed: 2 };

/**
 * A version beside the draft: both graphs drawn at once on the canvas - each
 * step the draft added, changed or removed marked on its card - and, beside
 * it, every changed step with the fields that changed in it.
 */
export function VersionComparison({
  version,
  draft,
  catalog,
}: {
  version: WorkflowGraph;
  draft: WorkflowGraph;
  catalog: NodeDefinition[];
}) {
  const t = useTranslations("workflows");
  const diff = useMemo(() => diffGraphs(version, draft), [version, draft]);
  const changes = useMemo(
    () => new Map([...diff.steps].map(([id, step]) => [id, step.change])),
    [diff],
  );
  const names = new Map(
    diff.union.nodes.map((node) => [
      node.id,
      node.label ??
        catalog.find(
          (item) => item.id === node.definition_id && item.version === node.definition_version,
        )?.name ??
        node.definition_id,
    ]),
  );
  const rows = [...diff.steps].sort(([, a], [, b]) => ORDER[a.change] - ORDER[b.change]);

  const fieldText = (field: ChangedField) =>
    field.kind === "setting" || field.kind === "input"
      ? t(`diffField.${field.kind}`, { name: field.name })
      : t(`diffField.${field.kind}`);

  return (
    <div className="flex h-full min-h-0 gap-4">
      <div className="min-h-0 min-w-0 flex-1">
        <VersionPreview graph={diff.union} catalog={catalog} changes={changes} />
      </div>
      <aside
        aria-label={t("diffListLabel")}
        className="border-border w-72 shrink-0 space-y-3 overflow-y-auto rounded-lg border p-3"
      >
        <p className="text-muted-foreground text-xs">
          {t("diffSummary", {
            steps: diff.steps.size,
            added: diff.edgesAdded,
            removed: diff.edgesRemoved,
          })}
        </p>
        {rows.length === 0 ? (
          <p className="text-sm">{t("diffNone")}</p>
        ) : (
          <ul className="space-y-2">
            {rows.map(([id, step]) => (
              <li key={id} className="space-y-1">
                <p className="flex items-center justify-between gap-2 text-sm font-medium">
                  <span className="truncate">{names.get(id)}</span>
                  <span
                    className={cn(
                      "shrink-0 rounded px-1.5 text-[10px] font-medium tracking-wide uppercase",
                      step.change === "added" &&
                        "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400",
                      step.change === "removed" && "bg-destructive/10 text-destructive",
                      step.change === "changed" && "bg-muted text-foreground",
                    )}
                  >
                    {t(`diff.${step.change}`)}
                  </span>
                </p>
                {step.fields.length > 0 && (
                  <ul className="text-muted-foreground space-y-0.5 pl-2 text-xs">
                    {step.fields.map((field) => (
                      <li key={fieldText(field)}>{fieldText(field)}</li>
                    ))}
                  </ul>
                )}
              </li>
            ))}
          </ul>
        )}
      </aside>
    </div>
  );
}
