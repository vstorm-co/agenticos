"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Bot, FileText, History } from "lucide-react";
import { useTranslations } from "next-intl";

import { DeleteSkillDialog } from "@/components/skills/delete-skill-dialog";
import { EditSkillDialog } from "@/components/skills/edit-skill-dialog";
import { NewForkDialog } from "@/components/skills/new-fork-dialog";
import { ReturnForkDialog } from "@/components/skills/return-fork-dialog";
import { SkillAgents } from "@/components/skills/skill-agents";
import { SkillContent } from "@/components/skills/skill-content";
import { SkillHistory } from "@/components/skills/skill-history";
import {
  eachAgentOnce,
  lineOf,
  shownAgents,
  type ShownAgents,
} from "@/components/skills/skill-lines";
import { CheckRunning } from "@/components/skills/check-running";
import type { CheckedDraft } from "@/components/skills/skill-check-dialog";
import { SkillChecks } from "@/components/skills/skill-checks";
import { SkillPageHeader, type Merges } from "@/components/skills/skill-page-header";
import { SkillTestQuestions } from "@/components/skills/skill-test-questions";
import { SkillUsageCard } from "@/components/skills/skill-usage";
import { ErrorState, LoadingState } from "@/components/states";
import { ResourceUnavailable } from "@/components/states/resource-unavailable";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui";
import { useSkill } from "@/hooks";
import { usePermissions } from "@/hooks/use-permissions";
import { useSkillAgents, useSkillForks, useSkillVersions } from "@/hooks/use-skill-versions";
import { useUrlState } from "@/hooks/use-url-state";
import { ApiError, getErrorMessage } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import { Perm } from "@/types/permissions";
import type { SkillAgentUsage, SkillFork } from "@/types/skill-versions";

/** The tabs `?tab=` may open, in the order they are drawn. */
const TABS = ["agents", "content", "history"];

/**
 * One skill: the agents that use it and the version each is served, every version
 * it has had, and its main line and forks.
 *
 * What the page shows - everyone, one state or one fork - is `?show=`, and a fork
 * chosen there is also the line History lists and Edit saves to.
 */
export function SkillDetails({ id }: { id: string }) {
  const t = useTranslations("skills.page");
  const tc = useTranslations("common");
  const tErrors = useTranslations("errors");
  const router = useRouter();
  const { can } = usePermissions();
  const [tabParam, setTabParam] = useUrlState("tab");
  const tab = tabParam !== null && TABS.includes(tabParam) ? tabParam : "agents";
  const [showParam, setShowParam] = useUrlState("show");
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<CheckedDraft | null>(null);
  // The editor is heavy to draw, so the button says it is opening until it is.
  const [opening, startOpening] = useTransition();
  const [deleting, setDeleting] = useState(false);
  const [forkFrom, setForkFrom] = useState<string | null>(null);
  const [returning, setReturning] = useState<SkillFork | null>(null);
  const { skill, error, remove } = useSkill(id);
  const lines = useSkillForks(id);
  const agents = useSkillAgents(id);
  const mainVersions = useSkillVersions(id, null, 0);

  if (error instanceof ApiError && [403, 404].includes(error.status)) {
    return <ResourceUnavailable back={ROUTES.SKILLS} label={tc("back")} />;
  }
  // Forks name the lines `?show=`, History and Edit act on, and main's newest version
  // counts who an edit of main reaches, so nothing is drawn on a guess about either.
  const failed = error ?? lines.error ?? mainVersions.error;
  if (failed) return <ErrorState description={getErrorMessage(failed, tErrors)} />;
  if (skill === undefined || lines.isLoading || mainVersions.isLoading) {
    return <LoadingState variant="pending" />;
  }
  const { forks } = lines;

  const asked = shownAgents(showParam);
  const forkId = lineOf(asked);
  const fork = forks.find((one) => one.id === forkId) ?? null;
  // A link to a fork that has since been archived shows everyone.
  const shown: ShownAgents = forkId !== null && fork === null ? "all" : asked;
  const base = skill.latest_version_id;
  // Counted by the server, so agents the reader cannot see and every serving environment count.
  const followers = fork === null ? (mainVersions.versions[0]?.agents ?? 0) : fork.agents;
  // A checked text is edited on the line it was checked on, whichever the page shows.
  const editChecked = (checked: CheckedDraft) => {
    setDraft(checked);
    if (checked.forkId !== (fork?.id ?? null)) {
      setShowParam(checked.forkId === null ? "main" : `fork:${checked.forkId}`);
    }
    setEditing(true);
  };
  // Reading a check's results asks runs:view; stopping or deciding one asks edit access too.
  const checks = can(Perm.runsView);
  const decides = checks && skill.can_edit === true;
  // A new fork offers the agents to move onto it, so it waits for their list; a list
  // that could not be read is said on the Agents tab.
  const listed = agents.agents?.items;

  return (
    <div className="space-y-6">
      <SkillPageHeader
        skill={skill}
        line={fork?.name ?? null}
        improveHref={`${ROUTES.SKILL_DETAIL(id)}/improve/new${fork === null ? "" : `?fork=${fork.id}`}`}
        merges={mergesOf(id, fork)}
        onReturn={
          fork !== null && fork.latest === null && returnable(agents.agents?.items, fork.id)
            ? { fork: fork.name, open: () => setReturning(fork) }
            : null
        }
        onEdit={() => startOpening(() => setEditing(true))}
        opening={opening}
        onFork={
          skill.can_edit && base !== null && listed !== undefined ? () => setForkFrom(base) : null
        }
        onDelete={skill.can_edit ? () => setDeleting(true) : null}
      />
      {decides && <CheckRunning skillId={id} forkId={fork?.id ?? null} onEdit={editChecked} />}
      <Tabs
        value={tab}
        onValueChange={(next) => setTabParam(next === "agents" ? null : next)}
        className="space-y-4"
      >
        <TabsList>
          <TabsTrigger value="agents" data-tour="skill-agents-tab">
            <Bot className="mr-1.5 size-4 shrink-0" aria-hidden />
            {t("tabs.agents")}
          </TabsTrigger>
          <TabsTrigger value="content" data-tour="skill-content-tab">
            <FileText className="mr-1.5 size-4 shrink-0" aria-hidden />
            {t("tabs.content")}
          </TabsTrigger>
          <TabsTrigger value="history" data-tour="skill-history-tab">
            <History className="mr-1.5 size-4 shrink-0" aria-hidden />
            {t("tabs.history")}
          </TabsTrigger>
        </TabsList>
        <TabsContent value="agents" className="space-y-4">
          <SkillAgents
            skillId={id}
            skillName={skill.name}
            mainLatest={skill.version}
            seesChecks={can(Perm.runsView)}
            agents={agents.agents}
            error={agents.error}
            forks={forks}
            shown={shown}
            onShow={(next) => setShowParam(next === "all" ? null : next)}
          />
          <SkillTestQuestions
            skillId={id}
            canCreate={skill.can_edit === true && can(Perm.datasetsEdit)}
          />
          {can(Perm.runsView) && <SkillUsageCard skillId={id} />}
        </TabsContent>
        <TabsContent value="content">
          <SkillContent
            skillId={id}
            versionId={fork === null ? base : (fork.latest?.id ?? fork.base.id)}
            label={
              fork === null
                ? t("tree.number", { number: skill.version })
                : t("tree.forkNumber", {
                    name: fork.name,
                    number: fork.latest?.number ?? fork.base.number,
                  })
            }
          />
        </TabsContent>
        <TabsContent value="history" className="space-y-4">
          <SkillHistory
            key={fork?.id ?? "main"}
            skillId={id}
            forkId={fork?.id ?? null}
            forkName={fork?.name ?? null}
            latestId={fork === null ? skill.latest_version_id : (fork.latest?.id ?? null)}
            canEdit={skill.can_edit === true}
            forks={forks}
            onLine={(next) => setShowParam(next === null ? "main" : `fork:${next}`)}
          />
          {checks && (
            <SkillChecks
              key={`checks:${fork?.id ?? "main"}`}
              skillId={id}
              forkId={fork?.id ?? null}
              canDecide={decides}
              onEdit={editChecked}
            />
          )}
        </TabsContent>
      </Tabs>
      {editing && (
        <EditSkillDialog
          skill={skill}
          fork={fork}
          followers={followers}
          readers={eachAgentOnce(
            (agents.agents?.items ?? []).filter(
              (usage) =>
                !usage.draft_only &&
                (fork === null
                  ? usage.binding.state === "main"
                  : usage.binding.fork?.id === fork.id),
            ),
          ).map((usage) => usage.agent.name)}
          canCheck={can(Perm.runsView)}
          draft={draft ?? undefined}
          onClose={() => {
            setEditing(false);
            setDraft(null);
          }}
          onDelete={() => setDeleting(true)}
        />
      )}
      {deleting && (
        <DeleteSkillDialog
          skill={skill}
          agents={agents.agents}
          agentsError={agents.error}
          deleting={remove.isPending}
          onClose={() => setDeleting(false)}
          onDelete={async (removeFromAgents) => {
            await remove.mutateAsync(removeFromAgents);
            router.push(ROUTES.SKILLS);
          }}
        />
      )}
      {returning !== null && (
        <ReturnForkDialog skillId={id} fork={returning} onClose={() => setReturning(null)} />
      )}
      {forkFrom !== null && listed !== undefined && (
        <NewForkDialog
          skill={skill}
          baseId={forkFrom}
          agents={listed}
          onClose={() => setForkFrom(null)}
          onCreated={(created) => {
            setForkFrom(null);
            setShowParam(`fork:${created}`);
          }}
        />
      )}
    </div>
  );
}

/**
 * Whether returning the fork to main can move any agent: one the reader may change,
 * bound to the fork itself. Each agent is moved with its own permissions, so the
 * skill's edit access and runs:view decide nothing here.
 */
function returnable(usages: SkillAgentUsage[] | undefined, forkId: string): boolean {
  return (usages ?? []).some((usage) => usage.can_change && usage.binding.fork?.id === forkId);
}

/**
 * Where the fork shown merges with main: catching up while main has moved past it, and
 * moving to main once it has a version of its own. A fork without one has nothing to
 * merge yet - its agents return to main instead.
 */
function mergesOf(skillId: string, fork: SkillFork | null): Merges | null {
  if (fork === null) return null;
  if (fork.latest === null) return { fork: fork.name, catchUp: null, toMain: null, empty: true };
  const href = (merge: string) =>
    `${ROUTES.SKILL_DETAIL(skillId)}/improve/new?fork=${fork.id}&merge=${merge}`;
  return {
    fork: fork.name,
    catchUp: fork.behind_main > 0 ? href("catch_up") : null,
    toMain: href("to_main"),
  };
}
