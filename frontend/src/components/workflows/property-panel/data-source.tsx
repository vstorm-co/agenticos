"use client";

import { Braces } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "@/components/ui";
import { plainType } from "@/lib/workflows/plain-types";
import type { Uuid } from "@/lib/workflows/types";
import { cn } from "@/lib/utils";

import type { SourceCandidate } from "./bindings";

/**
 * A candidate as a builder reads it: the step's name, then the field - "Run an
 * agent › text". The port is named only when the step has more than one that
 * offers something, and the whole output reads as the step alone.
 */
export function sourceText(
  candidate: SourceCandidate,
  names: ReadonlyMap<Uuid, string>,
  candidates: readonly SourceCandidate[],
): string {
  const step = names.get(candidate.nodeId) ?? candidate.nodeLabel;
  const path = pathText(candidate, candidates);
  return path === null ? step : `${step} › ${path}`;
}

/** The part of `sourceText` after the step, or null for a step's whole output. */
function pathText(
  candidate: SourceCandidate,
  candidates: readonly SourceCandidate[],
): string | null {
  const ports = new Set(
    candidates.filter((other) => other.nodeId === candidate.nodeId).map((other) => other.port),
  );
  const path = [
    ...(ports.size > 1 ? [candidate.portLabel] : []),
    ...(candidate.fieldPath.length > 0 ? [candidate.fieldPath.join(".")] : []),
  ];
  return path.length === 0 ? null : path.join(" › ");
}

/**
 * The "{ }" beside a parameter: every value an earlier step hands on that the
 * parameter can take, grouped by step, each with the kind of value it is.
 * Picking one hands it to `onPick` - inserted into text, or read as the value.
 */
export function DataSourceMenu({
  candidates,
  names,
  label,
  disabled,
  pressed,
  onPick,
}: {
  candidates: readonly SourceCandidate[];
  names: ReadonlyMap<Uuid, string>;
  /** What the button says it does, for its tooltip and a screen reader. */
  label: string;
  disabled?: boolean;
  /** Whether the parameter reads its value from a step now. */
  pressed?: boolean;
  onPick: (candidate: SourceCandidate) => void;
}) {
  const t = useTranslations("workflows");
  const steps = [...new Set(candidates.map((candidate) => candidate.nodeId))];
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        aria-label={label}
        title={label}
        disabled={disabled}
        className={cn(
          "text-muted-foreground hover:bg-accent hover:text-foreground focus-visible:ring-ring flex h-6 items-center gap-1 rounded-md px-1.5 text-[11px] font-medium outline-none focus-visible:ring-2 disabled:opacity-50",
          pressed && "bg-accent text-foreground",
        )}
      >
        <Braces aria-hidden="true" className="size-3.5" />
        {t("dataSourceButton")}
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="max-h-80 w-72 overflow-y-auto">
        {candidates.length === 0 ? (
          <p className="text-muted-foreground px-2 py-3 text-xs">{t("bindingNoSources")}</p>
        ) : (
          steps.map((step) => (
            <div key={step}>
              <DropdownMenuLabel className="text-muted-foreground text-xs font-medium">
                {names.get(step) ?? step}
              </DropdownMenuLabel>
              {candidates
                .filter((candidate) => candidate.nodeId === step)
                .map((candidate) => (
                  <DropdownMenuItem key={candidate.key} onSelect={() => onPick(candidate)}>
                    <span className="truncate font-mono text-xs">
                      {pathText(candidate, candidates) ?? t("dataSourceWhole")}
                    </span>
                    <span className="text-muted-foreground ml-auto shrink-0 text-xs">
                      {t(`dataType.${plainType(candidate.typeToken)}`)}
                    </span>
                  </DropdownMenuItem>
                ))}
            </div>
          ))
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
