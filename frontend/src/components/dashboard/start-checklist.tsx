"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowRight, Check, X } from "lucide-react";
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

interface Step {
  id: string;
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
export function StartChecklist({ orgId }: { orgId: string }) {
  const { can } = usePermissions();
  return can(Perm.agentsEdit) ? <BuilderChecklist orgId={orgId} /> : <Checklist orgId={orgId} />;
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

function BuilderChecklist({ orgId }: { orgId: string }) {
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
    ...(channels ? [{ id: "channel", done: bots.length > 0, href: ROUTES.CHANNELS }] : []),
  ];
  return <Checklist orgId={orgId} more={organization} />;
}

function Checklist({ orgId, more = [] }: { orgId: string; more?: Step[] }) {
  const t = useTranslations("dashboard.startChecklist");
  const ask = useArchitectAskStore((state) => state.ask);
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
  const go = (step: Step, className: string, children: React.ReactNode) =>
    step.href ? (
      <Link href={step.href} className={className}>
        {children}
      </Link>
    ) : (
      <button type="button" onClick={() => ask(t("agentAsk"))} className={className}>
        {children}
      </button>
    );

  return (
    <Card className="mt-6">
      <CardContent className="space-y-3.5 p-5">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold">{t("title")}</h2>
            <p className="text-muted-foreground text-xs">
              {t("progress", { done: steps.length - left, total: steps.length })}
            </p>
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
        <div
          className="bg-muted h-1 overflow-hidden rounded-full"
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={steps.length}
          aria-valuenow={steps.length - left}
          aria-label={t("title")}
        >
          <div
            className="bg-success h-full rounded-full transition-[width]"
            style={{ width: `${((steps.length - left) / steps.length) * 100}%` }}
          />
        </div>
        {/* The one thing to do next, said once and plainly; the rest is a
            compact record rather than ten boxes with lines through them. */}
        {next &&
          go(
            next,
            "group bg-muted/60 hover:bg-accent flex w-full items-center justify-between gap-3 rounded-lg px-3 py-2.5 text-left text-sm transition-colors",
            <>
              <span className="min-w-0">
                <span aria-hidden className="text-muted-foreground block text-xs">
                  {t("next")}
                </span>
                <span className="font-medium">{t(`steps.${next.id}`)}</span>
                <span className="text-muted-foreground block text-xs">{t(`hints.${next.id}`)}</span>
              </span>
              <ArrowRight
                className="text-muted-foreground group-hover:text-foreground h-4 w-4 shrink-0 transition-colors"
                aria-hidden
              />
            </>,
          )}
        <ol className="flex flex-wrap gap-x-4 gap-y-1.5">
          {steps
            .filter((step) => step !== next)
            .map((step) => (
              <li key={step.id}>
                {go(
                  step,
                  cn(
                    "hover:text-foreground flex items-center gap-1.5 text-xs transition-colors",
                    step.done ? "text-muted-foreground" : "text-foreground",
                  ),
                  <>
                    <span
                      className={cn(
                        "flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded-full border",
                        step.done && "bg-success border-success text-white",
                      )}
                    >
                      {step.done && <Check className="h-2.5 w-2.5" aria-hidden />}
                      {step.done && <span className="sr-only">{t("doneLabel")}</span>}
                    </span>
                    {t(`steps.${step.id}`)}
                  </>,
                )}
              </li>
            ))}
        </ol>
      </CardContent>
    </Card>
  );
}
