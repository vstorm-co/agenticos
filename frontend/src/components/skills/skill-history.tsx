"use client";

import { useState, useTransition } from "react";
import Link from "next/link";
import { ChevronDown, GitBranch, RotateCcw } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { toast } from "sonner";

import { Button, ConfirmDialog, ListCard, PAGE_SIZE, Pager, Skeleton } from "@/components/ui";
import { ErrorState } from "@/components/states";
import { usePermissions } from "@/hooks/use-permissions";
import { useSkillImprovementHistory } from "@/hooks/use-skill-improvement";
import { useSkillVersions, useSkillVersionWrites } from "@/hooks/use-skill-versions";
import { getErrorMessage } from "@/lib/api-error";
import { cn, formatDateTime } from "@/lib/utils";
import { Perm } from "@/types/permissions";
import type { SkillFork, SkillVersionSummary } from "@/types/skill-versions";
import { ImproveSessions, sessionHref } from "./improve-sessions";
import { VersionDiff } from "./version-diff";

/**
 * Every version of one line, newest first, each with what it changed.
 *
 * Restore brings an earlier version back as the line's newest, which every agent
 * following the line gets at once - so it asks first, and only an editor sees it.
 * The line's Improve sessions follow, each tied to the version it applied.
 */
export function SkillHistory({
  skillId,
  forkId,
  forkName,
  latestId,
  canEdit,
  forks,
  onLine,
}: {
  skillId: string;
  /** The fork whose history this is; null for main. */
  forkId: string | null;
  forkName: string | null;
  /** The line's newest version, which a restore is written over. */
  latestId: string | null;
  canEdit: boolean;
  /** The lines to switch between: main, then each fork. */
  forks: SkillFork[];
  onLine: (forkId: string | null) => void;
}) {
  const t = useTranslations("skills.page.history");
  const tErrors = useTranslations("errors");
  const [page, setPage] = useState(0);
  const [open, setOpen] = useState<string | null>(null);
  const [restoring, setRestoring] = useState<SkillVersionSummary | null>(null);
  const [asking, startAsking] = useTransition();
  const [pressed, setPressed] = useState<string | null>(null);
  const { versions, total, isLoading, error } = useSkillVersions(skillId, forkId, page);
  const { can } = usePermissions();
  const history = useSkillImprovementHistory(skillId, forkId, { enabled: can(Perm.runsView) });
  const madeBy = new Map(
    history.sessions.flatMap((session) =>
      session.applied_version_id === null ? [] : [[session.applied_version_id, session] as const],
    ),
  );
  const { restore } = useSkillVersionWrites(skillId);
  const line = forkName === null ? t("main") : t("fork", { name: forkName });
  // A fork numbers its versions from 1 too, so its own say whose they are.
  const label = (number: number) =>
    t("versionLabel", { number, name: forkName ?? "", fork: forkName === null ? "no" : "yes" });
  const base = forks.find((fork) => fork.id === forkId)?.base.number;

  return (
    <div className="space-y-4">
      <ListCard
        title={t("title", { line })}
        counted={isLoading ? null : t("versionCount", { count: total, line })}
        controls={
          forks.length > 0 && (
            <div className="flex flex-wrap gap-1.5" role="group" aria-label={t("lines")}>
              {[
                { id: null, label: t("main") },
                ...forks.map((fork) => ({ id: fork.id, label: t("fork", { name: fork.name }) })),
              ].map((choice) => (
                <button
                  key={choice.id ?? "main"}
                  type="button"
                  aria-pressed={choice.id === forkId}
                  onClick={() => onLine(choice.id)}
                  className={cn(
                    "rounded-full border px-2.5 py-1 text-xs font-medium transition-colors",
                    choice.id === forkId
                      ? "bg-primary text-primary-foreground border-transparent"
                      : "text-muted-foreground hover:bg-accent hover:text-foreground border-border",
                  )}
                >
                  {choice.label}
                </button>
              ))}
            </div>
          )
        }
        headerTour="skill-history"
      >
        {error ? (
          <ErrorState description={getErrorMessage(error, tErrors)} />
        ) : isLoading ? (
          <Skeleton className="m-4 h-32" />
        ) : versions.length === 0 && base !== undefined ? (
          <p className="text-muted-foreground px-4 py-6 text-sm">
            {t("forkEmpty", { number: base })}
          </p>
        ) : (
          <ol className="divide-border divide-y">
            {versions.map((version) => (
              <li key={version.id} className="space-y-3 px-4 py-3">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <VersionLine
                    version={version}
                    label={label}
                    starts={forks.filter((fork) => fork.started_from.id === version.id)}
                    session={
                      madeBy.has(version.id)
                        ? sessionHref(skillId, madeBy.get(version.id)!.id)
                        : null
                    }
                  />
                  <div className="flex shrink-0 items-center gap-1">
                    <Button
                      variant="ghost"
                      size="sm"
                      aria-expanded={open === version.id}
                      onClick={() => setOpen(open === version.id ? null : version.id)}
                    >
                      <ChevronDown className="h-4 w-4" aria-hidden />
                      {open === version.id ? t("hideChanges") : t("showChanges")}
                    </Button>
                    {canEdit && latestId !== null && version.id !== latestId && (
                      <Button
                        variant="outline"
                        size="sm"
                        loading={asking && pressed === version.id}
                        onClick={() => {
                          setPressed(version.id);
                          startAsking(() => setRestoring(version));
                        }}
                        aria-label={t("restoreVersion", { version: label(version.number) })}
                      >
                        <RotateCcw className="h-4 w-4" aria-hidden />
                        {t("restore")}
                      </Button>
                    )}
                  </div>
                </div>
                {open === version.id && (
                  <VersionDiff
                    skillId={skillId}
                    versionId={version.id}
                    previousId={version.previous?.id ?? null}
                  />
                )}
              </li>
            ))}
          </ol>
        )}
        {total > PAGE_SIZE && (
          <Pager
            page={page}
            pageCount={Math.ceil(total / PAGE_SIZE)}
            matched={total}
            total={total}
            onPage={setPage}
            counted={t("versionCount", { count: total, line })}
          />
        )}
        {restoring !== null && latestId !== null && (
          <ConfirmDialog
            open
            onOpenChange={() => setRestoring(null)}
            title={t("restoreTitle", { version: label(restoring.number) })}
            description={
              forkName === null
                ? t("restoreMain", { version: label(restoring.number) })
                : t("restoreFork", { version: label(restoring.number), name: forkName })
            }
            confirmLabel={t("restore")}
            loading={restore.isPending}
            onConfirm={async () => {
              try {
                const made = await restore.mutateAsync({
                  versionId: restoring.id,
                  baseVersionId: latestId,
                });
                toast.success(
                  t("restored", { version: label(restoring.number), made: label(made.number) }),
                );
              } catch (refusal) {
                toast.error(getErrorMessage(refusal, tErrors));
              }
              setRestoring(null);
            }}
          />
        )}
      </ListCard>
      {can(Perm.runsView) && (
        <ImproveSessions
          skillId={skillId}
          sessions={history.sessions}
          isLoading={history.isLoading}
          error={history.error}
          more={history.more}
          loadingMore={history.loadingMore}
          onMore={history.loadMore}
          versionLabel={(id) => {
            const version = versions.find((item) => item.id === id);
            return version ? label(version.number) : null;
          }}
        />
      )}
    </div>
  );
}

/** `v12 · Improve · Anna · 1 Nov 14:05 · used by 2 agents`, and the forks started from it. */
function VersionLine({
  version,
  label,
  starts,
  session,
}: {
  version: SkillVersionSummary;
  label: (number: number) => string;
  starts: SkillFork[];
  /** The Improve session that applied this version, when the reader may open it. */
  session: string | null;
}) {
  const t = useTranslations("skills.page.history");
  const locale = useLocale();
  return (
    <div className="min-w-0 space-y-0.5">
      <p className="text-sm">
        <span className="font-mono font-medium">{label(version.number)}</span>{" "}
        <span className="text-muted-foreground">
          {version.restored_from !== null
            ? t("restoredFrom", { version: label(version.restored_from.number) })
            : t(`source.${version.source}`)}
        </span>
      </p>
      <p className="text-muted-foreground text-xs">
        {t("madeBy", {
          who: version.created_by?.name ?? t("unknownAuthor"),
          when: formatDateTime(version.created_at, locale),
          agents: version.agents,
        })}
      </p>
      {session !== null && (
        <Link className="text-xs underline underline-offset-4" href={session}>
          {t("fromSession")}
        </Link>
      )}
      {starts.map((fork) => (
        <p key={fork.id} className="text-xs">
          <GitBranch className="text-muted-foreground mr-1 inline size-3" aria-hidden />
          {t("forkStarts", { name: fork.name })}
        </p>
      ))}
    </div>
  );
}
