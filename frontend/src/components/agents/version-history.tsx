"use client";

import { useMemo, useState } from "react";
import { GitCompare, Undo2 } from "lucide-react";

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
import type { AgentSpec, AgentVersion } from "@/types/agents";

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
}

/** The draft is a comparison target with no version id of its own. */
const DRAFT = "__draft__";

/**
 * What changed between two versions of an agent, and the way back to either.
 *
 * The diff is over the spec's YAML rather than over fields, and deliberately:
 * a spec is instructions, capability bindings, tool renames, tool descriptions,
 * budgets and model settings, and a per-field comparison would be a list of
 * every field somebody remembered to add to it. The text is the whole
 * configuration, so the diff is the whole change — including the tool
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
      <ol className="space-y-2">
        {versions.map((version) => (
          <li
            key={version.id}
            className="flex flex-wrap items-center gap-3 rounded-md border p-3 text-sm"
          >
            <span className="font-mono">v{version.version}</span>
            <span className="text-muted-foreground min-w-0 flex-1 truncate">
              {version.note ?? "—"}
            </span>
            <span className="text-muted-foreground text-xs">
              {/* Who and when, together: a timeline that says only "when" makes
                  the next question ("who did this?") a database query. */}
              {version.published_by_email ?? "unknown author"}
              {version.created_at ? ` · ${formatDate(version.created_at)}` : ""}
            </span>
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
 * Two specs, side by side as a unified diff.
 *
 * Rendered from a stable JSON serialization rather than the YAML the export
 * endpoint produces: a diff has to be a statement about the configuration, and
 * key order that moves between two dumps would show as a change nobody made.
 */
function SpecDiff({ before, after }: { before: AgentSpec; after: AgentSpec }) {
  const lines = useMemo(() => diffLines(stableJson(before), stableJson(after)), [before, after]);
  const stat = diffStat(lines);
  const rows = useMemo(() => collapseUnchanged(lines), [lines]);

  if (stat.added === 0 && stat.removed === 0) {
    return <p className="text-muted-foreground text-sm">Identical — nothing changed.</p>;
  }

  return (
    <div className="space-y-2">
      <p className="font-mono text-xs">
        <span className="text-emerald-600 dark:text-emerald-400">+{stat.added}</span>{" "}
        <span className="text-destructive">−{stat.removed}</span>
      </p>
      <div className="max-h-96 overflow-auto rounded-md border">
        <table className="w-full border-collapse font-mono text-xs">
          <tbody>
            {rows.map((row, index) =>
              row.kind === "gap" ? (
                <tr key={`gap-${index}`} className="bg-muted/40">
                  <td colSpan={3} className="text-muted-foreground px-3 py-1 text-center">
                    {row.hidden} unchanged {row.hidden === 1 ? "line" : "lines"}
                  </td>
                </tr>
              ) : (
                <tr
                  key={`${row.kind}-${row.before ?? ""}-${row.after ?? ""}-${index}`}
                  className={cn(
                    row.kind === "added" && "bg-emerald-500/10",
                    row.kind === "removed" && "bg-destructive/10",
                  )}
                >
                  <td className="text-muted-foreground w-10 border-r px-2 py-0.5 text-right select-none">
                    {row.before ?? ""}
                  </td>
                  <td className="text-muted-foreground w-10 border-r px-2 py-0.5 text-right select-none">
                    {row.after ?? ""}
                  </td>
                  <td className="w-full px-2 py-0.5 whitespace-pre-wrap">
                    <span className="text-muted-foreground select-none">
                      {row.kind === "added" ? "+" : row.kind === "removed" ? "−" : " "}
                    </span>{" "}
                    {row.text}
                  </td>
                </tr>
              ),
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/** JSON with its keys sorted, so a re-serialization is not a diff. */
export function stableJson(value: unknown): string {
  return JSON.stringify(value, (_key, node: unknown) => sortKeys(node), 2);
}

function sortKeys(node: unknown): unknown {
  if (node === null || typeof node !== "object" || Array.isArray(node)) return node;
  return Object.fromEntries(
    Object.entries(node as Record<string, unknown>).sort(([a], [b]) => a.localeCompare(b)),
  );
}
