"use client";

import { use, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Bot, GitBranch, History } from "lucide-react";
import { useTranslations } from "next-intl";

import { DeleteSkillDialog } from "@/components/skills/delete-skill-dialog";
import { EditSkillDialog } from "@/components/skills/edit-skill-dialog";
import { NewForkDialog } from "@/components/skills/new-fork-dialog";
import { SkillAgents } from "@/components/skills/skill-agents";
import { SkillHistory } from "@/components/skills/skill-history";
import { lineOf, shownAgents, type ShownAgents } from "@/components/skills/skill-lines";
import { SkillPageHeader } from "@/components/skills/skill-page-header";
import { SkillUsageCard } from "@/components/skills/skill-usage";
import { VersionTree } from "@/components/skills/version-tree";
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

/** The tabs `?tab=` may open, in the order they are drawn. */
const TABS = ["agents", "history", "tree"];

/**
 * One skill: the agents that use it and the version each is served, every version
 * it has had, and the tree of its main line and forks.
 *
 * What the page shows - everyone, one state or one fork - is `?show=`, and a fork
 * chosen there is also the line History lists and Edit saves to.
 */
export default function SkillPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const t = useTranslations("skills.page");
  const tc = useTranslations("common");
  const tErrors = useTranslations("errors");
  const router = useRouter();
  const { can } = usePermissions();
  const [tabParam, setTabParam] = useUrlState("tab");
  const tab = tabParam !== null && TABS.includes(tabParam) ? tabParam : "agents";
  const [showParam, setShowParam] = useUrlState("show");
  const [editing, setEditing] = useState(false);
  // The editor is heavy to draw, so the button says it is opening until it is.
  const [opening, startOpening] = useTransition();
  const [deleting, setDeleting] = useState(false);
  const [forkFrom, setForkFrom] = useState<string | null>(null);
  const { skill, error, remove } = useSkill(id);
  const lines = useSkillForks(id);
  const agents = useSkillAgents(id);
  const mainVersions = useSkillVersions(id, null, 0);

  if (error instanceof ApiError && [403, 404].includes(error.status)) {
    return <ResourceUnavailable back={ROUTES.SKILLS} label={tc("back")} />;
  }
  // Forks name the lines `?show=`, History and Edit act on, so nothing is drawn on a
  // guess about which one the address meant.
  const failed = error ?? lines.error;
  if (failed) return <ErrorState description={getErrorMessage(failed, tErrors)} />;
  if (skill === undefined || lines.isLoading) {
    return <LoadingState variant="skeleton-panel" rows={3} />;
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

  return (
    <div className="space-y-6">
      <SkillPageHeader
        skill={skill}
        line={fork?.name ?? null}
        onEdit={() => startOpening(() => setEditing(true))}
        opening={opening}
        onFork={skill.can_edit && base !== null ? () => setForkFrom(base) : null}
      />
      <Tabs
        value={tab}
        onValueChange={(next) => setTabParam(next === "agents" ? null : next)}
        className="space-y-4"
      >
        <TabsList>
          <TabsTrigger value="agents">
            <Bot className="mr-1.5 size-4 shrink-0" aria-hidden />
            {t("tabs.agents")}
          </TabsTrigger>
          <TabsTrigger value="history" data-tour="skill-history-tab">
            <History className="mr-1.5 size-4 shrink-0" aria-hidden />
            {t("tabs.history")}
          </TabsTrigger>
          <TabsTrigger value="tree" data-tour="skill-tree-tab">
            <GitBranch className="mr-1.5 size-4 shrink-0" aria-hidden />
            {t("tabs.tree")}
          </TabsTrigger>
        </TabsList>
        <TabsContent value="agents" className="space-y-4">
          <SkillAgents
            skillId={id}
            skillName={skill.name}
            mainLatest={skill.version}
            agents={agents.agents}
            error={agents.error}
            forks={forks}
            shown={shown}
            onShow={(next) => setShowParam(next === "all" ? null : next)}
          />
          {can(Perm.runsView) && <SkillUsageCard skillId={id} />}
        </TabsContent>
        <TabsContent value="history">
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
        </TabsContent>
        <TabsContent value="tree">
          <VersionTree
            mainLatest={skill.version}
            forks={forks}
            agents={agents.agents?.items ?? []}
            error={agents.error}
          />
        </TabsContent>
      </Tabs>
      {editing && (
        <EditSkillDialog
          skill={skill}
          fork={fork}
          followers={followers}
          onClose={() => setEditing(false)}
          onDelete={() => setDeleting(true)}
        />
      )}
      {deleting && (
        <DeleteSkillDialog
          skill={skill}
          agents={agents.agents}
          deleting={remove.isPending}
          onClose={() => setDeleting(false)}
          onDelete={async () => {
            await remove.mutateAsync();
            router.push(ROUTES.SKILLS);
          }}
        />
      )}
      {forkFrom !== null && (
        <NewForkDialog
          skill={skill}
          baseId={forkFrom}
          agents={agents.agents?.items ?? []}
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
