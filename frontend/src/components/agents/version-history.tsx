"use client";

import { useMemo, useState } from "react";
import { GitCompare, Undo2 } from "lucide-react";
import { stringify } from "yaml";

import {
  Badge,
  Button,
  PaginationBar,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { LoadingState } from "@/components/states";
import { useAgentVersion, useAgentVersions, VERSIONS_PAGE_SIZE } from "@/hooks";
import { collapseUnchanged, diffLines, diffStat } from "@/lib/diff";
import { cn, formatDate, timeAgo } from "@/lib/utils";
import type { AgentEnvironment, AgentSpec, AgentVersion } from "@/types/agents";
import { useLocale, useTranslations } from "next-intl";

interface VersionHistoryProps {
  agentId: string;
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
  const t = useTranslations("agents");
  const targets = environments.filter((environment) => environment.version_id !== version.id);
  if (targets.length === 0) return null;
  return (
    <Select
      value=""
      disabled={promoting}
      onValueChange={(environmentId) => onPromote(environmentId, version.id)}
    >
      <SelectTrigger
        className="w-36"
        aria-label={t("promoteVersionTo", { version: version.version })}
      >
        <SelectValue placeholder={t("promote")} />
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
  currentVersionId,
  draftSpec,
  canRestore,
  onRestore,
  restoring,
  environments = [],
  onPromote,
  promoting,
}: VersionHistoryProps) {
  const t = useTranslations("agents");
  // `timeAgo` reads its words from the shared `time` namespace, not this one.
  const tTime = useTranslations("time");
  const locale = useLocale();
  const [page, setPage] = useState(0);
  const { versions, total, isLoading } = useAgentVersions(agentId, {
    skip: page * VERSIONS_PAGE_SIZE,
    limit: VERSIONS_PAGE_SIZE,
  });
  // Newest against the one before it: the comparison somebody opening a history
  // almost always wants, and the one that needs no explaining. Adopted from the
  // first page once it arrives, and only while nothing else has been picked -
  // paging must not silently re-aim a comparison the reader set up.
  const [rightId, setRightId] = useState<string>(DRAFT);
  const [leftId, setLeftId] = useState<string | null>(null);
  // The comparison must not depend on which page is on screen: picking v12 and
  // then turning the page left the trigger blank and the version unpickable.
  // Asked for only when the history is longer than a page - below that this
  // page *is* every version, and a second request would fetch what is already
  // here.
  const paged = total > VERSIONS_PAGE_SIZE;
  const { versions: allVersions } = useAgentVersions(paged ? agentId : null);
  const pickable = paged ? allVersions : versions;
  const newestId = versions[0]?.id ?? null;
  const [seenNewest, setSeenNewest] = useState<string | null>(null);
  if (page === 0 && newestId !== null && newestId !== seenNewest) {
    setSeenNewest(newestId);
    if (leftId === null) setLeftId(newestId);
  }

  const left = useAgentVersion(agentId, leftId);
  const right = useAgentVersion(agentId, rightId === DRAFT ? null : rightId);

  const rightSpec = rightId === DRAFT ? draftSpec : right.version?.spec;
  const comparing = leftId !== null && (rightId === DRAFT || right.version !== undefined);

  if (isLoading && versions.length === 0) return <LoadingState variant="skeleton-list" rows={3} />;
  if (total === 0) {
    return <p className="text-muted-foreground text-sm">{t("neverPublished")}</p>;
  }

  return (
    <div className="space-y-4">
      {/* A rail rather than a table: this is a timeline, and the version a
          reader is looking for is found by its place in it as often as by its
          number. The row is one line at any width - the note truncates and the
          controls keep their place, so twenty rows scan as twenty rows. */}
      <ol className="relative rounded-md border">
        {versions.map((version, index) => {
          const live = version.id === currentVersionId;
          const serving = environments.filter(
            (environment) => environment.version_id === version.id,
          );
          return (
            <li
              key={version.id}
              className={cn(
                "relative flex items-center gap-3 py-2.5 pr-3 pl-11 text-sm",
                index > 0 && "border-t",
                live && "bg-brand-subtle/40",
              )}
            >
              {/* The rail: a line down the card and a dot per publish, filled
                  on the version that is serving. It stops at the last row so
                  the timeline does not appear to continue past the page. */}
              <span
                aria-hidden
                className={cn(
                  "bg-border absolute top-0 left-[1.35rem] w-px",
                  index === 0 ? "top-1/2" : "top-0",
                  index === versions.length - 1 ? "h-1/2" : "h-full",
                )}
              />
              <span
                aria-hidden
                className={cn(
                  "absolute left-4 h-2.5 w-2.5 rounded-full border-2",
                  live ? "border-brand bg-brand" : "border-border bg-card",
                )}
              />
              <span className="w-10 shrink-0 font-mono text-xs font-semibold">
                v{version.version}
              </span>
              {/* The note is the row's headline - the "why" somebody wrote at
                  publish. Who and when follow it on the same line now: stacked,
                  every row was two lines tall to carry one fact each. */}
              <span
                className={cn(
                  "min-w-0 flex-1 truncate",
                  !version.note && "text-muted-foreground italic",
                )}
                title={version.note ?? undefined}
              >
                {version.note ?? t("noNote")}
              </span>
              <span className="text-muted-foreground hidden shrink-0 text-xs sm:inline">
                {version.published_by_email ?? t("unknownAuthor")}
              </span>
              {version.created_at && (
                <span
                  className="text-muted-foreground shrink-0 text-xs"
                  title={formatDate(version.created_at, locale)}
                >
                  {timeAgo(version.created_at, tTime, locale)}
                </span>
              )}
              {/* Which environments serve this exact version - the fact that
                  turns "is dev ahead of prod" from archaeology into a glance. */}
              {serving.map((environment) => (
                <Badge key={environment.id} variant="secondary" className="shrink-0 font-mono">
                  {environment.name}
                </Badge>
              ))}
              {live && <Badge className="shrink-0">{t("live")}</Badge>}
              <div className="flex shrink-0 items-center gap-1">
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => setLeftId(version.id)}
                  aria-label={t("compareVersion", { version: version.version })}
                  aria-pressed={leftId === version.id}
                  className={cn("h-8 w-8 p-0", leftId === version.id && "bg-accent")}
                >
                  <GitCompare className="h-4 w-4" />
                </Button>
                {onPromote && canRestore && (
                  <PromoteMenu
                    version={version}
                    environments={environments}
                    onPromote={onPromote}
                    promoting={promoting}
                  />
                )}
                {canRestore && !live && (
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={restoring}
                    onClick={() => onRestore(version.id)}
                    aria-label={t("restoreVersion", { version: version.version })}
                    title={t("restore2")}
                    className="h-8 w-8 p-0"
                  >
                    <Undo2 className="h-4 w-4" />
                  </Button>
                )}
              </div>
            </li>
          );
        })}
      </ol>

      {/* Only when there is more than one page of it. A history of four
          versions is not a paged list, and a pager under it is furniture. */}
      {total > VERSIONS_PAGE_SIZE && (
        <PaginationBar
          page={page}
          pageSize={VERSIONS_PAGE_SIZE}
          total={total}
          isLoading={isLoading}
          onPage={setPage}
        />
      )}

      <div className="space-y-2 rounded-md border p-3">
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span className="text-muted-foreground">{t("comparing")}</span>
          <Select value={leftId ?? ""} onValueChange={setLeftId}>
            <SelectTrigger className="w-32" aria-label={t("compareFrom")}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {pickable.map((version) => (
                <SelectItem key={version.id} value={version.id}>
                  v{version.version}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <span className="text-muted-foreground">{t("with")}</span>
          <Select value={rightId} onValueChange={setRightId}>
            <SelectTrigger className="w-32" aria-label={t("compare")}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {/* The draft is what most comparisons are against: "what have I
                  changed since the version that is running". */}
              <SelectItem value={DRAFT}>{t("draft")}</SelectItem>
              {pickable.map((version) => (
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
          <p className="text-muted-foreground text-sm">{t("pickTwoVersionsCompare")}</p>
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
  const t = useTranslations("agents");
  const lines = useMemo(() => diffLines(specText(before), specText(after)), [before, after]);
  const stat = diffStat(lines);
  const rows = useMemo(() => collapseUnchanged(lines), [lines]);

  if (stat.added === 0 && stat.removed === 0) {
    return <p className="text-muted-foreground text-sm">{t("identicalNothingChanged")}</p>;
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
                    {t("unchangedLines", { count: row.hidden })}
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
