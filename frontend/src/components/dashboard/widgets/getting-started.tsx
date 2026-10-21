"use client";

import Link from "next/link";
import { Check, ChevronRight, PartyPopper } from "lucide-react";
import { useTranslations } from "next-intl";

import { WidgetFrame } from "../widget-frame";
import { WidgetEmptyBody, WidgetSkeleton } from "../widget-states";
import type { DashboardWidgetProps } from "./types";
import { useAgents } from "@/hooks";
import { useRecentConversations } from "@/hooks/use-dashboard-data";
import { useMcpConnections } from "@/hooks/use-mcp-connections";
import { useOrgTriggers } from "@/hooks/use-org-triggers";
import { ROUTES } from "@/lib/constants";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/stores";
import { useArchitectAskStore } from "@/stores/architect-ask-store";

/** The agents every organization opens with, which are not one a person built. */
const SEEDED = new Set(["agenticos", "architect"]);

type StepKey = "profile" | "chat" | "routine" | "connection" | "agent";

interface Step {
  key: StepKey;
  done: boolean;
  /** Where the step is done; a step with none is a question to the Architect. */
  href?: string;
}

const ROW =
  "bg-muted/60 flex h-full w-full items-start gap-2.5 rounded-xl p-3 text-left transition-colors";

/**
 * The next things worth doing here, from what the person has actually done (#2301).
 *
 * Five steps, each ticked off by real state rather than a checklist somebody
 * clicks: what agents know about them, a first conversation, a routine of their
 * own, a service connected with their own account, and an agent they built. No
 * endpoint of its own - every step is a read another page already makes.
 */
export function GettingStartedWidget({ title, hint, options }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.getting-started");
  const ask = useArchitectAskStore((state) => state.ask);
  const user = useAuthStore((state) => state.user);
  const conversations = useRecentConversations(1);
  const { triggers, isLoading: triggersLoading } = useOrgTriggers();
  const { connections, isLoading: connectionsLoading } = useMcpConnections();
  const { agents, isLoading: agentsLoading } = useAgents();

  const frame = (body: React.ReactNode) => (
    <WidgetFrame title={title} hint={hint} options={options}>
      {body}
    </WidgetFrame>
  );
  if (conversations.isLoading || triggersLoading || connectionsLoading || agentsLoading) {
    return frame(<WidgetSkeleton />);
  }

  const steps: Step[] = [
    { key: "profile", done: Boolean(user?.job_title), href: ROUTES.SETTINGS_PROFILE },
    { key: "chat", done: conversations.conversations.length > 0, href: ROUTES.CHAT },
    {
      key: "routine",
      done: triggers.some((trigger) => trigger.created_by_user_id === user?.id),
      href: ROUTES.ROUTINES,
    },
    { key: "connection", done: connections.length > 0, href: ROUTES.MCP_SERVERS },
    {
      key: "agent",
      done: agents.some((agent) => agent.owner_user_id === user?.id && !SEEDED.has(agent.slug)),
    },
  ];
  const left = steps.filter((step) => !step.done).length;
  if (left === 0) {
    return frame(
      <WidgetEmptyBody
        icon={PartyPopper}
        title={t("done.title")}
        description={t("done.description")}
      />,
    );
  }

  const content = (step: Step) => (
    <>
      <span
        className={cn(
          "mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border text-[11px]",
          step.done ? "bg-success border-transparent text-white" : "border-border",
        )}
      >
        {step.done && <Check className="h-3 w-3" aria-hidden />}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-sm font-medium">{t(`steps.${step.key}.title`)}</span>
        <span className="text-muted-foreground block text-xs">{t(`steps.${step.key}.body`)}</span>
      </span>
      {!step.done && <ChevronRight className="text-muted-foreground mt-0.5 h-4 w-4" />}
    </>
  );

  return frame(
    <div className="space-y-2">
      <p className="text-muted-foreground text-xs">
        {t("progress", { done: steps.length - left, total: steps.length })}
      </p>
      <ul className="grid gap-1.5 sm:grid-cols-2 xl:grid-cols-5">
        {steps.map((step) => (
          <li key={step.key}>
            {step.done ? (
              <div className={cn(ROW, "opacity-60")}>{content(step)}</div>
            ) : step.href ? (
              <Link href={step.href} className={cn(ROW, "hover:bg-muted")}>
                {content(step)}
              </Link>
            ) : (
              <button
                type="button"
                onClick={() => ask(t("agentAsk"))}
                className={cn(ROW, "hover:bg-muted")}
              >
                {content(step)}
              </button>
            )}
          </li>
        ))}
      </ul>
    </div>,
  );
}
