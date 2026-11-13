"use client";

import { useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { AlertTriangle } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { toast } from "sonner";

import {
  Alert,
  AlertDescription,
  Button,
  Checkbox,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { useSkillVersions, useSkillVersionWrites, versionPage } from "@/hooks/use-skill-versions";
import { getErrorMessage } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import { DIALOG_FORM } from "@/lib/dialog-sizes";
import { cn, formatDate, formatDateTime } from "@/lib/utils";
import type { BindingTarget } from "@/lib/skill-versions-api";
import type { SkillCheck } from "@/types/skill-checks";
import type { AgentCheckRef, SkillAgentUsage, SkillFork } from "@/types/skill-versions";
import { bindingLabel } from "./skill-lines";
import { AutoHeight } from "./auto-height";
import { shownState } from "@/components/skill-improvement/check-summary";
import { SkillCheckDialog } from "./skill-check-dialog";
import { VersionDiff } from "./version-diff";

/**
 * The version a choice reads now - main's newest, the pinned one, or a fork's newest
 * (its base on main until it has one) - and whether the agent already serves it.
 */
function reads(
  target: BindingTarget,
  usage: SkillAgentUsage,
  fork: SkillFork | undefined,
  mainLatest: number,
  mainId: (number: number) => string | undefined,
): { number: number; fork: string | null; served: boolean; id: string | undefined } {
  const served = usage.binding.version;
  const onMain = (number: number) => ({
    number,
    fork: null,
    served: served.fork_id === null && served.number === number,
    id: mainId(number),
  });
  if (target.state === "main") return onMain(mainLatest);
  if (target.state === "pinned") return onMain(target.version);
  if (!fork?.latest) return onMain(fork?.base.number ?? mainLatest);
  return {
    number: fork.latest.number,
    fork: fork.name,
    served: served.id === fork.latest.id,
    id: fork.latest.id,
  };
}

/** What an update check found on the agent it checked, as the agent's own check reads. */
function foundOn(check: SkillCheck, agentId: string): AgentCheckRef {
  const row = check.agents.find((agent) => agent.agent.id === agentId);
  return {
    check_id: check.id,
    version_id: check.applied_version_id ?? "",
    state: row?.state ?? "unknown",
    sample: row?.sample ?? null,
    at: check.created_at,
  };
}

/** Whether two bindings name the same thing to follow. */
function sameTarget(a: BindingTarget, b: BindingTarget): boolean {
  if (a.state === "pinned" && b.state === "pinned") return a.version === b.version;
  if (a.state === "fork" && b.state === "fork") return a.fork_id === b.fork_id;
  return a.state === b.state;
}

/**
 * Move one agent to main, a pinned main version, or a fork.
 *
 * It publishes a new version of the agent from its published one, with only this
 * binding changed, so nothing unfinished in its draft goes live. A version other
 * than the one the agent serves now has not been checked on it, and the person
 * says so before the change is made; leaving main is said too, since the agent
 * then stops getting main's new versions.
 */
export function ChangeVersionDialog({
  skillId,
  skillName,
  usage,
  forks,
  mainLatest,
  seesChecks,
  onClose,
}: {
  skillId: string;
  skillName: string;
  usage: SkillAgentUsage;
  forks: SkillFork[];
  /** Main's newest version number. */
  mainLatest: number;
  /** Whether the reader is told what checks found, which needs `runs:view`. */
  seesChecks: boolean;
  onClose: () => void;
}) {
  const t = useTranslations("skills.page.changeVersion");
  const tPage = useTranslations("skills.page");
  const tHistory = useTranslations("skills.page.history");
  const tCheck = useTranslations("skillImprovement.agents");
  const tErrors = useTranslations("errors");
  const tCommon = useTranslations("common");
  const locale = useLocale();
  const router = useRouter();
  const { changeBinding } = useSkillVersionWrites(skillId);
  // A binding names its fork exactly when it reads one.
  const current: BindingTarget =
    usage.binding.state === "pinned"
      ? { state: "pinned", version: usage.binding.version.number }
      : usage.binding.fork
        ? { state: "fork", fork_id: usage.binding.fork.id }
        : { state: "main" };
  const [target, setTarget] = useState<BindingTarget>(current);
  const [understood, setUnderstood] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);
  const [updateCheck, setUpdateCheck] = useState<AgentCheckRef | null>(null);
  const unchanged = sameTarget(target, current);
  const name = usage.agent.name;
  const pinned = target.state === "pinned" ? String(target.version) : "";
  // Main numbers its versions from 1 without gaps, so every one of them can be pinned.
  const pinnable = Array.from({ length: mainLatest }, (_, index) => mainLatest - index);
  const firstPin = current.state === "pinned" ? current.version : pinnable[0];
  // Main's versions run newest first, so the page holding a picked one is known from its number.
  const pickedPage = target.state === "pinned" ? versionPage(mainLatest, target.version) : 0;
  const newest = useSkillVersions(skillId, null, 0);
  const around = useSkillVersions(skillId, null, pickedPage);
  const known = new Map(
    [...newest.versions, ...around.versions].map((version) => [version.number, version]),
  );
  const [diffing, setDiffing] = useState(false);
  const targetFork =
    target.state === "fork" ? forks.find((fork) => fork.id === target.fork_id) : undefined;
  const read = reads(target, usage, targetFork, mainLatest, (number) => known.get(number)?.id);
  // Whether the agent answered with or was checked on a version is known by its id, so
  // nothing is claimed about it, and nothing changed, until the page naming it is read.
  const pages = [newest, around];
  const unread = read.id === undefined && !unchanged;
  const reading = unread && pages.some((page) => page.isLoading);
  const unreadable = unread ? (pages.find((page) => page.error)?.error ?? null) : null;
  const held = reading || unreadable !== null;
  // The check run here of main's newest version on the pinned agent, still undecided.
  const update = current.state === "pinned" && target.state === "main" ? updateCheck : null;
  // A check that measured this very version on the agent answers what the warning asks.
  const checked = update ?? usage.checked_versions?.find((ref) => ref.version_id === read.id);
  const label =
    read.fork === null
      ? t("versionOption", { number: read.number })
      : t("forkVersion", { name: read.fork, number: read.number });
  // The agent has answered with it before, so moving there brings it nothing new.
  const answered = read.id !== undefined && (usage.answered_with ?? []).includes(read.id);
  // A check that could not measure the agent answers nothing: it is acknowledged instead.
  const needsAck =
    !unchanged && !read.served && !held && (checked ? checked.state === "unknown" : !answered);
  // A pinned agent caught up on main's newest version carries the check run for that move,
  // which decides it rather than leaving it waiting. A past result is decided already, and
  // the server refuses to decide a check twice, so it only informs the warning.
  const decided =
    update !== null
      ? { check_id: update.check_id, acknowledge_unknown: update.state === "unknown" && understood }
      : null;
  // The server refuses that move once the check found the agent worse.
  const staysPinned = update?.state === "worse";
  // Only main's newest version on a pinned agent can be checked on that agent alone.
  const canCheckFirst =
    needsAck && seesChecks && !checked && current.state === "pinned" && target.state === "main";
  const leavesMain = !unchanged && current.state === "main" && target.state !== "main";
  const picked = target.state === "pinned" ? known.get(target.version) : undefined;

  async function submit() {
    setError(null);
    try {
      const result = await changeBinding.mutateAsync({
        agentId: usage.agent.id,
        target,
        check: decided,
      });
      if (result.published) {
        const list = new Intl.ListFormat(locale, { type: "conjunction" });
        toast.success(
          t("published", {
            name,
            environments: list.format(
              result.environments.map((environment) => t("environmentName", { name: environment })),
            ),
            count: result.environments.length,
          }),
        );
      } else {
        toast.info(t("savedInDraft", { name }), {
          action: {
            label: t("openBuilder"),
            onClick: () => router.push(ROUTES.AGENT_DETAIL(usage.agent.id)),
          },
        });
      }
      onClose();
    } catch (refusal) {
      setError(getErrorMessage(refusal, tErrors));
    }
  }

  const option = (choice: BindingTarget, label: string, extra?: ReactNode) => (
    <label className="flex items-start gap-2 text-sm">
      <input
        type="radio"
        name="skill-binding"
        className="mt-1"
        checked={
          target.state === choice.state && (choice.state !== "fork" || sameTarget(choice, target))
        }
        onChange={() => {
          setTarget(choice);
          setUnderstood(false);
        }}
      />
      <span className="min-w-0 flex-1 space-y-1.5">
        <span className="block">{label}</span>
        {extra}
      </span>
    </label>
  );

  if (checking) {
    return (
      <SkillCheckDialog
        skillId={skillId}
        change={{ updateAgentId: usage.agent.id }}
        forkId={null}
        onOpenChange={(open) => !open && setChecking(false)}
        onChecked={(check) => {
          setUpdateCheck(foundOn(check, usage.agent.id));
          setUnderstood(false);
          setChecking(false);
        }}
      />
    );
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className={DIALOG_FORM}>
        <DialogHeader>
          <DialogTitle>{t("title", { skill: skillName, name })}</DialogTitle>
          <DialogDescription>
            {t("now", { binding: bindingLabel(tPage, usage.binding) })}
          </DialogDescription>
        </DialogHeader>
        <AutoHeight>
          <fieldset className="space-y-3">
            <legend className="sr-only">{t("legend")}</legend>
            {option({ state: "main" }, t("followMain"))}
            {firstPin !== undefined &&
              option(
                { state: "pinned", version: firstPin },
                t("pin"),
                target.state === "pinned" && (
                  <Select
                    value={pinned}
                    onValueChange={(value) => {
                      setTarget({ state: "pinned", version: Number(value) });
                      setUnderstood(false);
                    }}
                  >
                    <SelectTrigger className="w-56" aria-label={t("pinVersion")}>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {pinnable.map((number) => {
                        const summary = known.get(number);
                        return (
                          <SelectItem key={number} value={String(number)}>
                            {summary
                              ? t("versionWhen", {
                                  number,
                                  when: formatDate(summary.created_at, locale),
                                })
                              : t("versionOption", { number })}
                          </SelectItem>
                        );
                      })}
                    </SelectContent>
                  </Select>
                ),
              )}
            {picked && (
              <div className="ml-6 space-y-2">
                <p className="text-muted-foreground text-xs">
                  {t("pinDetail", {
                    source:
                      picked.restored_from !== null
                        ? tHistory("restoredFrom", {
                            version: t("versionOption", { number: picked.restored_from.number }),
                          })
                        : tHistory(`source.${picked.source}`),
                    who: picked.created_by?.name ?? tHistory("unknownAuthor"),
                    when: formatDateTime(picked.created_at, locale),
                  })}
                </p>
                <Button
                  variant="link"
                  size="sm"
                  className="h-auto p-0"
                  onClick={() => setDiffing(!diffing)}
                >
                  {diffing ? tHistory("hideChanges") : tHistory("showChanges")}
                </Button>
                {diffing && (
                  <VersionDiff
                    skillId={skillId}
                    versionId={picked.id}
                    previousId={picked.previous?.id ?? null}
                  />
                )}
              </div>
            )}
            {forks.map((fork) => (
              <div key={fork.id}>
                {option({ state: "fork", fork_id: fork.id }, t("fork", { name: fork.name }))}
              </div>
            ))}
          </fieldset>
          <div className="space-y-2 pt-3 empty:hidden">
            {leavesMain && (
              <p className="text-sm">
                {targetFork
                  ? t("leavesMainFork", {
                      name,
                      fork: targetFork.name,
                      behind: targetFork.behind_main,
                    })
                  : t("leavesMain", { name })}
              </p>
            )}
            {!unchanged && !read.served && checked && (
              <p className={cn("text-sm", checked.state === "worse" && "text-warning")}>
                {t("checkedOn", {
                  version: label,
                  name,
                  state: tCheck(`state.${shownState(checked.state)}`),
                  when: formatDate(checked.at, locale),
                })}
              </p>
            )}
            {staysPinned && (
              <p role="alert" className="text-sm">
                {t("staysPinned", { version: label, name })}
              </p>
            )}
            {!unchanged && !read.served && answered && !checked && (
              <p className="text-muted-foreground text-sm">
                {t("answeredBefore", { version: label, name })}
              </p>
            )}
            {needsAck && (
              <Alert variant="warning">
                <AlertTriangle className="h-4 w-4" />
                <AlertDescription className="space-y-2">
                  <p>
                    {seesChecks
                      ? t("unchecked", { version: label, name })
                      : t("checksUnseen", { version: label, name })}
                  </p>
                  {canCheckFirst && (
                    <Button variant="outline" size="sm" onClick={() => setChecking(true)}>
                      {t("checkFirst")}
                    </Button>
                  )}
                  <div className="flex items-center gap-2">
                    <Checkbox
                      id="skill-binding-understood"
                      checked={understood}
                      onCheckedChange={(checked) => setUnderstood(checked === true)}
                    />
                    <Label htmlFor="skill-binding-understood">{t("understood")}</Label>
                  </div>
                </AlertDescription>
              </Alert>
            )}
          </div>
        </AutoHeight>
        <p className="text-muted-foreground text-sm">
          {usage.can_publish ? t("publishes", { name }) : t("savesToDraft", { name })}
        </p>
        {unreadable !== null && (
          <div role="alert" className="flex items-center justify-between gap-3 text-sm">
            <p className="text-destructive">{getErrorMessage(unreadable, tErrors)}</p>
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                for (const page of pages) void page.refetch();
              }}
            >
              {tCommon("retry")}
            </Button>
          </div>
        )}
        {error !== null && (
          <p role="alert" className="text-destructive text-sm">
            {error}
          </p>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            {t("cancel")}
          </Button>
          <Button
            onClick={() => void submit()}
            disabled={unchanged || held || staysPinned || (needsAck && !understood)}
            loading={changeBinding.isPending}
          >
            {usage.can_publish ? t("submit") : t("submitDraft")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
