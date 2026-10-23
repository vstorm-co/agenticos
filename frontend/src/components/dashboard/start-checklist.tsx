"use client";

import { useState } from "react";
import Link from "next/link";
import {
  Bot,
  CalendarClock,
  Check,
  ChevronRight,
  Library,
  MessageSquare,
  MessagesSquare,
  Plug,
  Rocket,
  UserPlus,
  UserRound,
  UsersRound,
  X,
  type LucideIcon,
} from "lucide-react";
import { useTranslations } from "next-intl";

import { Button, Card, CardContent } from "@/components/ui";
import {
  useAgents,
  useChannelBots,
  useGroups,
  useKnowledgeBases,
  useMembers,
  usePermissions,
} from "@/hooks";
import { useRecentConversations } from "@/hooks/use-dashboard-data";
import { useMcpConnections } from "@/hooks/use-mcp-connections";
import { useOrgTriggers } from "@/hooks/use-org-triggers";
import { ROUTES } from "@/lib/constants";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/stores";
import { useArchitectAskStore } from "@/stores/architect-ask-store";
import { Perm } from "@/types/permissions";

/** The agents every organization opens with, which are not one a person built. */
const SEEDED = new Set(["agenticos", "architect"]);

/** Each step's mark, so the list reads by shape as well as by word. */
const ICONS = {
  profile: UserRound,
  chat: MessageSquare,
  connection: Plug,
  routine: CalendarClock,
  agent: Bot,
  publish: Rocket,
  knowledge: Library,
  departments: UsersRound,
  teammate: UserPlus,
  channel: MessagesSquare,
} satisfies Record<string, LucideIcon>;

interface Step {
  id: keyof typeof ICONS;
  done: boolean;
  /** Where the step is done; a step with none is a question to the Architect. */
  href?: string;
}

const dismissedKey = (orgId: string) => `agenticos:start-checklist:${orgId}`;

function readDismissed(orgId: string): boolean {
  try {
    return window.localStorage.getItem(dismissedKey(orgId)) === "dismissed";
  } catch {
    return false;
  }
}

/**
 * The first things worth doing here, with what is already done ticked (#2072,
 * #2301).
 *
 * One card for everybody: their own steps first - what agents know about them, a
 * conversation, an account connected, a routine, an agent they built - and, for
 * whoever builds agents, the organization's after them. Each step's state is read
 * from what exists, not recorded, so doing a step anywhere ticks it here. On the
 * dashboard until every step is done or they close it; closing it is a
 * per-browser convenience.
 */
export function StartChecklist({ orgId, className }: { orgId: string; className?: string }) {
  const { can } = usePermissions();
  return can(Perm.agentsEdit) ? (
    <BuilderChecklist orgId={orgId} className={className} />
  ) : (
    <Checklist orgId={orgId} className={className} />
  );
}

function usePersonalSteps(): { steps: Step[]; loading: boolean } {
  const user = useAuthStore((state) => state.user);
  const conversations = useRecentConversations(1);
  const { triggers, isLoading: triggersLoading } = useOrgTriggers();
  const { connections, isLoading: connectionsLoading } = useMcpConnections();
  const { agents, isLoading: agentsLoading } = useAgents();
  return {
    loading: conversations.isLoading || triggersLoading || connectionsLoading || agentsLoading,
    steps: [
      { id: "profile", done: Boolean(user?.job_title), href: ROUTES.SETTINGS_PROFILE },
      { id: "chat", done: conversations.conversations.length > 0, href: ROUTES.CHAT },
      { id: "connection", done: connections.length > 0, href: ROUTES.MCP_SERVERS },
      {
        id: "routine",
        done: triggers.some((trigger) => trigger.created_by_user_id === user?.id),
        href: ROUTES.ROUTINES,
      },
      {
        id: "agent",
        done: agents.some((agent) => agent.owner_user_id === user?.id && !SEEDED.has(agent.slug)),
      },
    ],
  };
}

function BuilderChecklist({ orgId, className }: { orgId: string; className?: string }) {
  const { can } = usePermissions();
  const channels = can(Perm.channelsManage);
  const { agents } = useAgents();
  const { kbs } = useKnowledgeBases();
  const { groups } = useGroups(orgId);
  const { members } = useMembers(orgId);
  const { bots } = useChannelBots(channels);
  const organization: Step[] = [
    {
      id: "publish",
      done: agents.some((agent) => agent.status === "published"),
      href: ROUTES.AGENTS,
    },
    { id: "knowledge", done: kbs.length > 0, href: ROUTES.RAG },
    { id: "departments", done: groups.length > 0, href: ROUTES.GROUPS },
    { id: "teammate", done: members.length > 1, href: ROUTES.ORG_MEMBERS(orgId) },
    ...(channels ? [{ id: "channel" as const, done: bots.length > 0, href: ROUTES.CHANNELS }] : []),
  ];
  return <Checklist orgId={orgId} more={organization} className={className} />;
}

function Checklist({
  orgId,
  more = [],
  className,
}: {
  orgId: string;
  more?: Step[];
  className?: string;
}) {
  const t = useTranslations("dashboard.startChecklist");
  const [dismissed, setDismissed] = useState(() => readDismissed(orgId));
  const personal = usePersonalSteps();
  const steps = [...personal.steps, ...more];
  const left = steps.filter((step) => !step.done).length;
  const next = steps.find((step) => !step.done);

  if (dismissed || personal.loading || left === 0) return null;

  const dismiss = () => {
    setDismissed(true);
    try {
      window.localStorage.setItem(dismissedKey(orgId), "dismissed");
    } catch {
      // Nowhere to keep it; it stays closed for this visit.
    }
  };
  const done = steps.length - left;
  // Headed only when there are two: a member's card is their own steps alone.
  const groups =
    more.length > 0
      ? [
          { key: "you", steps: personal.steps },
          { key: "organization", steps: more },
        ]
      : [{ key: null, steps: personal.steps }];

  return (
    <Card className={cn("@container mt-6 flex flex-col", className)}>
      <CardContent className="flex flex-1 flex-col gap-4 p-5">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 space-y-2">
            <h2 className="text-sm font-semibold">{t("title")}</h2>
            <div className="flex items-center gap-2.5">
              <div
                className="bg-muted h-1.5 w-28 overflow-hidden rounded-full"
                role="progressbar"
                aria-valuemin={0}
                aria-valuemax={steps.length}
                aria-valuenow={done}
                aria-label={t("title")}
              >
                <div
                  className="bg-success h-full rounded-full transition-[width]"
                  style={{ width: `${(done / steps.length) * 100}%` }}
                />
              </div>
              <span className="text-muted-foreground text-xs">
                {t("progress", { done, total: steps.length })}
              </span>
            </div>
          </div>
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            aria-label={t("dismiss")}
            onClick={dismiss}
          >
            <X className="h-4 w-4" />
          </Button>
        </div>
        <div className="grid gap-x-6 gap-y-4 @2xl:grid-cols-2">
          {groups.map((group) => (
            <section key={group.key ?? "steps"} className="space-y-1">
              {group.key && (
                <h3 className="text-muted-foreground px-2.5 text-[11px] font-medium tracking-wide uppercase">
                  {t(`groups.${group.key}`)}
                </h3>
              )}
              <ol className="space-y-0.5">
                {group.steps.map((step) => (
                  <li key={step.id}>
                    <StepRow step={step} next={step === next} />
                  </li>
                ))}
              </ol>
            </section>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

/**
 * One step: its mark, ticked when done; what it is for while it is not; the next
 * one raised and labelled. A step with no page is a question to the Architect.
 */
function StepRow({ step, next }: { step: Step; next: boolean }) {
  const t = useTranslations("dashboard.startChecklist");
  const ask = useArchitectAskStore((state) => state.ask);
  const Icon = ICONS[step.id];
  // A done step is one quiet line; what is left gets its mark and what it is for.
  const className = cn(
    "group flex w-full items-center gap-3 rounded-lg px-2.5 text-left transition-colors",
    step.done ? "py-1" : "py-2",
    next ? "bg-muted/70 hover:bg-muted" : "hover:bg-muted/50",
  );
  const body = (
    <>
      {step.done ? (
        <span className="flex w-8 shrink-0 justify-center">
          <span className="bg-success flex h-4 w-4 items-center justify-center rounded-full text-white">
            <Check className="h-2.5 w-2.5" aria-hidden />
            <span className="sr-only">{t("doneLabel")}</span>
          </span>
        </span>
      ) : (
        <span className="bg-card text-foreground shadow-card flex h-8 w-8 shrink-0 items-center justify-center rounded-lg">
          <Icon className="h-4 w-4" aria-hidden />
        </span>
      )}
      <span className="min-w-0 flex-1">
        <span
          className={cn(
            "block truncate text-sm",
            step.done ? "text-muted-foreground" : "text-foreground font-medium",
          )}
        >
          {t(`steps.${step.id}`)}
        </span>
        {!step.done && (
          <span className="text-muted-foreground block truncate text-xs">
            {t(`hints.${step.id}`)}
          </span>
        )}
      </span>
      {next && (
        <span className="bg-foreground text-background shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium">
          {t("next")}
        </span>
      )}
      {!step.done && (
        <ChevronRight
          className="text-muted-foreground group-hover:text-foreground h-4 w-4 shrink-0 transition-colors"
          aria-hidden
        />
      )}
    </>
  );
  return step.href ? (
    <Link href={step.href} className={className}>
      {body}
    </Link>
  ) : (
    <button type="button" onClick={() => ask(t("agentAsk"))} className={className}>
      {body}
    </button>
  );
}
