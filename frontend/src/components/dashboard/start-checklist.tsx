"use client";

import { useState } from "react";
import Link from "next/link";
import {
  Bot,
  CalendarClock,
  Check,
  ArrowRight,
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
  const open = steps.filter((step) => !step.done);
  const [next, ...later] = open;

  if (dismissed || personal.loading || !next) return null;

  const dismiss = () => {
    setDismissed(true);
    try {
      window.localStorage.setItem(dismissedKey(orgId), "dismissed");
    } catch {
      // Nowhere to keep it; it stays closed for this visit.
    }
  };
  const done = steps.filter((step) => step.done);
  const NextIcon = ICONS[next.id];

  return (
    <Card className={cn("mt-6 flex flex-col", className)}>
      <CardContent className="flex flex-1 flex-col gap-5 p-5">
        <div className="flex items-center gap-4">
          <ProgressRing done={done.length} total={steps.length} />
          <div className="min-w-0 flex-1">
            <h2 className="text-base font-semibold tracking-tight">{t("title")}</h2>
            <p className="text-muted-foreground text-sm">{t("left", { count: open.length })}</p>
          </div>
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7 self-start"
            aria-label={t("dismiss")}
            onClick={dismiss}
          >
            <X className="h-4 w-4" />
          </Button>
        </div>

        {/* The one thing to do now, said plainly and with its own button. */}
        <div className="bg-muted/60 flex items-start gap-3.5 rounded-xl p-4">
          <span className="bg-card text-foreground shadow-card flex h-10 w-10 shrink-0 items-center justify-center rounded-xl">
            <NextIcon className="h-5 w-5" aria-hidden />
          </span>
          <div className="min-w-0 flex-1 space-y-3">
            <div>
              <p className="text-muted-foreground text-xs">{t("next")}</p>
              <p className="text-sm font-semibold">{t(`steps.${next.id}`)}</p>
              <p className="text-muted-foreground text-sm">{t(`hints.${next.id}`)}</p>
            </div>
            <StepAction step={next} className="h-8">
              {t("start")}
              <ArrowRight className="h-3.5 w-3.5" aria-hidden />
            </StepAction>
          </div>
        </div>

        {later.length > 0 && (
          <ol className="-mt-1 space-y-0.5">
            {later.map((step) => {
              const Icon = ICONS[step.id];
              return (
                <li key={step.id}>
                  <StepLink
                    step={step}
                    className="group hover:bg-muted/50 flex w-full items-center gap-3 rounded-lg px-2 py-2 text-left transition-colors"
                  >
                    <span className="bg-muted flex h-7 w-7 shrink-0 items-center justify-center rounded-lg">
                      <Icon className="h-3.5 w-3.5" aria-hidden />
                    </span>
                    <span className="min-w-0 flex-1 truncate text-sm">{t(`steps.${step.id}`)}</span>
                    <ChevronRight
                      className="text-muted-foreground group-hover:text-foreground h-4 w-4 shrink-0 transition-colors"
                      aria-hidden
                    />
                  </StepLink>
                </li>
              );
            })}
          </ol>
        )}

        {done.length > 0 && (
          <div className="mt-auto space-y-2 border-t pt-4">
            <p className="text-muted-foreground text-xs">{t("doneHeading")}</p>
            <ul className="flex flex-wrap gap-1.5">
              {done.map((step) => (
                <li key={step.id}>
                  <StepLink
                    step={step}
                    className="bg-muted/60 text-muted-foreground hover:text-foreground inline-flex items-center gap-1.5 rounded-full py-1 pr-2.5 pl-1.5 text-xs transition-colors"
                  >
                    <span className="bg-success flex h-3.5 w-3.5 items-center justify-center rounded-full text-white">
                      <Check className="h-2.5 w-2.5" aria-hidden />
                    </span>
                    {t(`steps.${step.id}`)}
                  </StepLink>
                </li>
              ))}
            </ul>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

/** How far along, as a ring with the count in it. */
function ProgressRing({ done, total }: { done: number; total: number }) {
  const t = useTranslations("dashboard.startChecklist");
  const radius = 22;
  const circumference = 2 * Math.PI * radius;
  return (
    <div
      className="relative h-14 w-14 shrink-0"
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={total}
      aria-valuenow={done}
      aria-valuetext={t("progress", { done, total })}
      aria-label={t("title")}
    >
      <svg viewBox="0 0 56 56" className="h-14 w-14 -rotate-90" aria-hidden>
        <circle cx="28" cy="28" r={radius} className="stroke-muted" strokeWidth="5" fill="none" />
        <circle
          cx="28"
          cy="28"
          r={radius}
          className="stroke-success transition-[stroke-dashoffset] duration-500"
          strokeWidth="5"
          strokeLinecap="round"
          fill="none"
          strokeDasharray={circumference}
          strokeDashoffset={circumference * (1 - done / total)}
        />
      </svg>
      <span className="absolute inset-0 flex items-center justify-center text-xs font-semibold tabular-nums">
        {t("ratio", { done, total })}
      </span>
    </div>
  );
}

/** A step's own place: its page, or for an agent of one's own, a question to the Architect. */
function StepLink({
  step,
  className,
  children,
}: {
  step: Step;
  className: string;
  children: React.ReactNode;
}) {
  const t = useTranslations("dashboard.startChecklist");
  const ask = useArchitectAskStore((state) => state.ask);
  return step.href ? (
    <Link href={step.href} className={className}>
      {children}
    </Link>
  ) : (
    <button type="button" onClick={() => ask(t("agentAsk"))} className={className}>
      {children}
    </button>
  );
}

/** The next step's button: the same destination as its row, drawn as the card's one call to act. */
function StepAction({
  step,
  className,
  children,
}: {
  step: Step;
  className?: string;
  children: React.ReactNode;
}) {
  const t = useTranslations("dashboard.startChecklist");
  const ask = useArchitectAskStore((state) => state.ask);
  return step.href ? (
    <Button asChild size="sm" className={className}>
      <Link href={step.href}>{children}</Link>
    </Button>
  ) : (
    <Button size="sm" className={className} onClick={() => ask(t("agentAsk"))}>
      {children}
    </Button>
  );
}
