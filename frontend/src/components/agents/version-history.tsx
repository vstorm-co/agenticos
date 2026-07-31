"use client";

import { useMemo, useState } from "react";
import { GitCompare, Undo2 } from "lucide-react";
import { stringify } from "yaml";

import {
  Badge,
  Button,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { LoadingState } from "@/components/states";
import { useAgentVersion } from "@/hooks";
import { collapseUnchanged, diffLines, diffStat } from "@/lib/diff";
import { cn, formatDate } from "@/lib/utils";
import type { AgentEnvironment, AgentSpec, AgentVersion } from "@/types/agents";

interface VersionHistoryProps {
  agentId: string;
  versions: AgentVersion[];
  /** The version that is live, so the list can say which one that is. */
  currentVersionId: string | null;
  /** The spec being edited, so a version can be compared against it. */
  draftSpec: AgentSpec;
  canRestore: boolean;
  onRestore: (versionId: string) => void;
  restoring?: boolean;
  /** Named environments, so each row can say where it is serving. */
  environments?: AgentEnvironment[];
  /** Repoint one environment at this row's version - promotion. */
  onPromote?: (environmentId: string, versionId: string) => void;
  promoting?: boolean;
}

/** The draft is a comparison target with no version id of its own. */
const DRAFT = "__draft__";

/**
 * "Promote to…" for one version row: pick an environment not already serving
 * it. A select rather than one button because an agent can have several
 * environments, and the row must say which one is being repointed.
 */
function PromoteMenu({
  version,
  environments,
  onPromote,
  promoting,
}: {
  version: AgentVersion;
  environments: AgentEnvironment[];
  onPromote: (environmentId: string, versionId: string) => void;
  promoting?: boolean;
}) {
  const targets = environments.filter(
    (environment) => environment.version_id !== version.id,
  );
  if (targets.length === 0) return null;
  return (
    <Select
      value=""
      disabled={promoting}
      onValueChange={(environmentId) => onPromote(environmentId, version.id)}
    >
      <SelectTrigger className="w-36" aria-label={`Promote v${version.version} to…`}>
        <SelectValue placeholder="Promote to…" />
      </SelectTrigger>
      <SelectContent>
        {targets.map((environment) => (
          <SelectItem key={environment.id} value={environment.id}>
            {environment.name} (v{environment.version} → v{version.version})
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

/**
 * What changed between two versions of an agent, and the way back to either.
 *
 * The diff is over the spec's YAML rather than over fields, and deliberately:
 * a spec is instructions, capability bindings, tool renames, tool descriptions,
 * budgets and model settings, and a per-field comparison would be a list of
 * every field somebody remembered to add to it. The text is the whole
 * configuration, so the diff is the whole change - including the tool
 * description somebody reworded, which is exactly the edit a field-by-field
 * view would have omitted.
 */
export function VersionHistory({
  agentId,
  versions,
  currentVersionId,
  draftSpec,
  canRestore,
  onRestore,
  restoring,
  environments = [],
  onPromote,
  promoting,
}: VersionHistoryProps) {
  // Newest against the one before it: the comparison somebody opening a history
  // almost always wants, and the one that needs no explaining.
  const [rightId, setRightId] = useState<string>(DRAFT);
  const [leftId, setLeftId] = useState<string | null>(versions[0]?.id ?? null);

  const left = useAgentVersion(agentId, leftId);
  const right = useAgentVersion(agentId, rightId === DRAFT ? null : rightId);

  const rightSpec = rightId === DRAFT ? draftSpec : right.version?.spec;
  const comparing = leftId !== null && (rightId === DRAFT || right.version !== undefined);

  if (versions.length === 0) {
    return <p className="text-muted-foreground text-sm">Never published.</p>;
  }

  return (
    <div className="space-y-4">
      <ol className="divide-y rounded-md border">
        {versions.map((version) => (
          <li
            key={version.id}
            className={cn(
              "flex flex-wrap items-center gap-3 p-3 text-sm",
              // The live row is the one fact somebody scans this list for.
              version.id === currentVersionId && "bg-brand-subtle/40",
            )}
          >
            <span className="bg-muted w-12 shrink-0 rounded-md px-2 py-1 text-center font-mono text-xs font-semibold">
              v{version.version}
            </span>
            <div className="min-w-0 flex-1">
              {/* The note is the row's headline - it is the "why" somebody
                  wrote at publish - and the who/when reads under it instead of
                  competing with it on one line. */}
              <p className={cn("truncate", !version.note && "text-muted-foreground italic")}>
                {version.note ?? "No note"}
              </p>
              <p className="text-muted-foreground mt-0.5 text-xs">
                {version.published_by_email ?? "unknown author"}
                {version.created_at ? ` · ${formatDate(version.created_at)}` : ""}
              </p>
            </div>
            {/* Which environments serve this exact version - the fact that
                turns "is dev ahead of prod" from archaeology into a glance. */}
            {environments
              .filter((environment) => environment.version_id === version.id)
              .map((environment) => (
                <Badge key={environment.id} variant="secondary" className="font-mono">
                  {environment.name}
                </Badge>
              ))}
            {version.id === currentVersionId && <Badge>live</Badge>}
            <Button
              size="sm"
              variant="ghost"
              onClick={() => setLeftId(version.id)}
              aria-label={`Compare v${version.version}`}
              aria-pressed={leftId === version.id}
              className={cn(leftId === version.id && "bg-accent")}
            >
              <GitCompare className="h-4 w-4" />
              Compare
            </Button>
            {onPromote && canRestore && (
              <PromoteMenu
                version={version}
                environments={environments}
                onPromote={onPromote}
                promoting={promoting}
              />
            )}
            {canRestore && version.id !== currentVersionId && (
              <Button
                size="sm"
                variant="outline"
                disabled={restoring}
                onClick={() => onRestore(version.id)}
              >
                <Undo2 className="h-4 w-4" />
                Restore
              </Button>
            )}
          </li>
        ))}
      </ol>

      <div className="space-y-2 rounded-md border p-3">
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span className="text-muted-foreground">Comparing</span>
          <Select value={leftId ?? ""} onValueChange={setLeftId}>
            <SelectTrigger className="w-32" aria-label="Compare from">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {versions.map((version) => (
                <SelectItem key={version.id} value={version.id}>
                  v{version.version}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <span className="text-muted-foreground">with</span>
          <Select value={rightId} onValueChange={setRightId}>
            <SelectTrigger className="w-32" aria-label="Compare to">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {/* The draft is what most comparisons are against: "what have I
                  changed since the version that is running". */}
              <SelectItem value={DRAFT}>Draft</SelectItem>
              {versions.map((version) => (
                <SelectItem key={version.id} value={version.id}>
                  v{version.version}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {left.isLoading || right.isLoading ? (
          <LoadingState variant="skeleton-list" rows={4} />
        ) : comparing && left.version && rightSpec ? (
          <SpecDiff before={left.version.spec} after={rightSpec} />
        ) : (
          <p className="text-muted-foreground text-sm">Pick two versions to compare.</p>
        )}
      </div>
    </div>
  );
}

/**
 * Two specs as a unified diff.
 *
 * Diffed over YAML rather than JSON, because the diff is read, not parsed:
 * YAML drops the braces, quotes and commas, and it renders a multi-line
 * instruction as its actual lines - so editing one paragraph shows as that
 * paragraph, not as one endless string with `\n` in it. Keys are sorted at
 * serialization, so key order that moves between two dumps cannot show as a
 * change nobody made.
 */
function SpecDiff({ before, after }: { before: AgentSpec; after: AgentSpec }) {
  const lines = useMemo(() => diffLines(specText(before), specText(after)), [before, after]);
  const stat = diffStat(lines);
  const rows = useMemo(() => collapseUnchanged(lines), [lines]);

  if (stat.added === 0 && stat.removed === 0) {
    return <p className="text-muted-foreground text-sm">Identical - nothing changed.</p>;
  }

  return (
    <div className="space-y-2">
      <p className="font-mono text-xs">
        <span className="text-emerald-600 dark:text-emerald-400">+{stat.added}</span>{" "}
        <span className="text-destructive">−{stat.removed}</span>
      </p>
      {/* No line-number gutters: they numbered a serialization nobody has a
          copy of, and two columns of them out-inked the diff itself. */}
      <div className="max-h-96 overflow-auto rounded-md border">
        <table className="w-full border-collapse font-mono text-xs leading-5">
          <tbody>
            {rows.map((row, index) =>
              row.kind === "gap" ? (
                <tr key={`gap-${index}`} className="bg-muted/40">
                  <td colSpan={2} className="text-muted-foreground px-3 py-1 text-center">
                    {row.hidden} unchanged {row.hidden === 1 ? "line" : "lines"}
                  </td>
                </tr>
              ) : (
                <tr
                  key={`${row.kind}-${row.before ?? ""}-${row.after ?? ""}-${index}`}
                  className={cn(
                    row.kind === "same" && "text-muted-foreground",
                    row.kind === "added" && "bg-emerald-500/10",
                    row.kind === "removed" && "bg-destructive/10",
                  )}
                >
                  <td className="text-muted-foreground w-6 px-2 py-0.5 text-center select-none">
                    {row.kind === "added" ? "+" : row.kind === "removed" ? "−" : ""}
                  </td>
                  <td className="w-full py-0.5 pr-2 whitespace-pre-wrap">{row.text}</td>
                </tr>
              ),
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/**
 * A spec as diffable text: YAML with its keys sorted, so a re-serialization is
 * not a diff, and with folding off, so a long line cannot reflow its neighbours
 * into changes.
 */
export function specText(value: unknown): string {
  return stringify(value, { sortMapEntries: true, lineWidth: 0 });
}
