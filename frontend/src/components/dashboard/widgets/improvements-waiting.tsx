"use client";

import Link from "next/link";
import { CircleCheck, FlaskConical, GitMerge, TrendingUp } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui";
import { useImprovementsAwaiting } from "@/hooks/use-improvements";
import { useSkillChecksAwaiting } from "@/hooks/use-skill-check";
import { useSkillProposalsAwaiting } from "@/hooks/use-skill-changes";
import { useSkillImprovementsAwaiting } from "@/hooks/use-skill-improvement";
import { usePermissions } from "@/hooks/use-permissions";
import { useBehindMain } from "@/hooks/use-skill-merge";
import { ROUTES } from "@/lib/constants";
import { stopOf } from "@/lib/improvement-steps";
import { Perm } from "@/types/permissions";
import { WidgetFrame } from "../widget-frame";
import { WidgetEmptyBody, WidgetErrorBody, WidgetSkeleton } from "../widget-states";
import type { DashboardWidgetProps } from "./types";

/** How many a card lists; the newest come first. */
const SHOWN = 5;

/** One waiting session, an agent's or a skill's, as the card lists it. */
interface Waiting {
  id: string;
  name: string;
  href: string;
  /** What the button does and where it leads; none for something the reader may not act on. */
  action: { label: string; href: string; icon: "improve" | "merge" | "check" } | null;
  what: string;
}

/** Which of the card's reads failed. */
type Source = "agents" | "skills" | "checks" | "proposals" | "behind";

const ICON = { improve: TrendingUp, merge: GitMerge, check: FlaskConical };

/**
 * Improvement sessions waiting for a person - an agent's or a skill's: stopped after
 * a step, or with a result to review - and checks of a skill change a person started,
 * running or waiting for a decision, newest first. Each opens where it waits. After
 * them, the skill changes agents proposed, then the pinned agents and forks main has
 * moved past, furthest behind first: a fork is caught up from here, a pinned agent on
 * its skill's page. Each is read apart, so one that fails leaves the others listed.
 */
export function ImprovementsWaitingWidget({ title, hint, options }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.improvements-waiting");
  const tErrors = useTranslations("dashboard.errors");
  const agents = useImprovementsAwaiting();
  const skills = useSkillImprovementsAwaiting();
  // The card is gated on reading runs; what main left behind is read with skills:view.
  const { can } = usePermissions();
  const readsSkills = can(Perm.skillsView);
  const behind = useBehindMain({ enabled: readsSkills });
  const checks = useSkillChecksAwaiting();
  // Proposals are decided under skills:edit, and listed only to who may decide them.
  const editsSkills = can(Perm.skillsEdit);
  const proposals = useSkillProposalsAwaiting({ enabled: editsSkills });
  const reads = { agents, skills, checks, proposals, behind };
  // Only the reads made count: one the reader may not make neither fails nor succeeds.
  const made = (Object.keys(reads) as Source[]).filter(
    (source) => (source !== "proposals" || editsSkills) && (source !== "behind" || readsSkills),
  );
  const isLoading = made.some((source) => reads[source].isLoading);
  const failed = made.filter((source) => reads[source].error);
  // A manual refetch ignores `enabled`, so the reads the reader may not make are left out.
  const refetch = () =>
    Promise.all([
      agents.refetch(),
      skills.refetch(),
      checks.refetch(),
      ...(editsSkills ? [proposals.refetch()] : []),
      ...(readsSkills ? [behind.refetch()] : []),
    ]);
  const what = (item: Parameters<typeof stopOf>[0] & { next_step_blocked?: unknown }) =>
    t(item.next_step_blocked ? "what.blocked" : `what.${stopOf(item) ?? "result"}`);
  const open = { label: t("open"), icon: "improve" as const };
  const checked = new Set(
    (checks.error ? [] : checks.checks).flatMap((item) =>
      item.proposal_id === null ? [] : [item.proposal_id],
    ),
  );
  const sessions: (Waiting & { createdAt: string })[] = [
    ...(agents.error ? [] : agents.sessions).map((item) => ({
      id: item.id,
      name: item.agent_name,
      href: ROUTES.AGENT_DETAIL(item.agent_id),
      action: { ...open, href: `${ROUTES.AGENT_DETAIL(item.agent_id)}/improve/${item.id}` },
      what: what(item),
      createdAt: item.created_at,
    })),
    ...(skills.error ? [] : skills.sessions).map((item) => ({
      id: item.id,
      name: t("skill", {
        name: item.skill_name,
        kind: item.fork_id === null ? "main" : "fork",
        line: item.line_name,
      }),
      href: ROUTES.SKILL_DETAIL(item.skill_id),
      action: { ...open, href: `${ROUTES.SKILL_DETAIL(item.skill_id)}/improve/${item.id}` },
      what: what(item),
      createdAt: item.created_at,
    })),
    ...(checks.error ? [] : checks.checks).map((item) => ({
      id: `check:${item.id}`,
      name: t("skill", {
        name: item.skill_name,
        kind: item.line.fork_id === null ? "main" : "fork",
        line: item.line.name,
      }),
      href: ROUTES.SKILL_DETAIL(item.skill_id),
      action: {
        label: t("open"),
        href: `${ROUTES.SKILL_DETAIL(item.skill_id)}?tab=history${item.line.fork_id === null ? "" : `&show=fork:${item.line.fork_id}`}&check=${item.id}`,
        icon: "check" as const,
      },
      what: t(`what.check.${item.status}`, { count: item.agents }),
      createdAt: item.created_at,
    })),
  ].sort((a, b) => b.createdAt.localeCompare(a.createdAt));
  const items: Waiting[] = [
    ...sessions,
    // A proposal under an open check is listed once, as that check.
    ...(proposals.error ? [] : proposals.changes)
      .filter((item) => !checked.has(item.id))
      .map((item) => ({
        id: `proposal:${item.id}`,
        name: t("proposal", { name: item.name, kind: item.skill_id === null ? "new" : "edit" }),
        href: ROUTES.SKILLS,
        action: { label: t("review"), href: ROUTES.SKILLS, icon: "check" as const },
        what: t("what.proposal", { count: item.reaches.length + item.reaches_hidden }),
      })),
    ...(behind.error ? [] : (behind.behind?.items ?? [])).map((item) => {
      const skill = ROUTES.SKILL_DETAIL(item.skill.id);
      return {
        // An agent can pin a skill itself and through a specialist: two rows, two keys.
        id: `behind:${item.kind}:${item.skill.id}:${item.kind === "fork" ? item.fork.id : item.agent.id}:${item.via_specialist ?? ""}`,
        name: t("behindName", {
          name: item.skill.name,
          kind: item.kind,
          line: item.kind === "fork" ? item.fork.name : item.agent.name,
          via: item.via_specialist ?? "",
          specialist: item.via_specialist === null ? "no" : "yes",
        }),
        href: skill,
        action: !item.can_act
          ? null
          : item.kind === "fork" && item.fork.changes > 0
            ? {
                label: t("catchUp"),
                href: `${skill}/improve/new?fork=${item.fork.id}&merge=catch_up`,
                icon: "merge" as const,
              }
            : { ...open, href: skill },
        what: t(`behind.${item.kind}`, {
          version: item.version.number,
          agents: item.agents,
          count: item.behind_main,
        }),
      };
    }),
  ];
  return (
    <WidgetFrame title={title} hint={hint} options={options}>
      {isLoading ? (
        <WidgetSkeleton />
      ) : failed.length === made.length ? (
        <WidgetErrorBody onRetry={() => refetch()} />
      ) : items.length === 0 ? (
        <WidgetEmptyBody
          icon={CircleCheck}
          title={t("empty.title")}
          description={t("empty.description")}
        />
      ) : (
        <ul className="divide-border divide-y text-sm">
          {items.slice(0, SHOWN).map((item) => (
            <li key={item.id} className="flex items-center justify-between gap-3 py-2">
              <span className="min-w-0 space-y-0.5">
                <Link href={item.href} className="block truncate font-medium">
                  {item.name}
                </Link>
                <span className="text-muted-foreground block truncate text-xs">{item.what}</span>
              </span>
              {item.action && (
                <Button asChild size="sm" variant="outline" className="shrink-0">
                  <Link href={item.action.href}>
                    <ActionIcon icon={item.action.icon} />
                    {item.action.label}
                  </Link>
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
      {!isLoading && failed.length > 0 && failed.length < made.length && (
        <div role="alert" className="text-muted-foreground flex items-center gap-2 text-xs">
          <span>
            {failed.map((source) => (
              <span key={source} className="block">
                {t("partial", { failed: source })}
              </span>
            ))}
          </span>
          <Button variant="link" size="sm" className="h-auto p-0" onClick={() => refetch()}>
            {tErrors("retry")}
          </Button>
        </div>
      )}
    </WidgetFrame>
  );
}

function ActionIcon({ icon }: { icon: keyof typeof ICON }) {
  const Icon = ICON[icon];
  return <Icon className="h-4 w-4" aria-hidden />;
}
