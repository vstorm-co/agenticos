"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";
import {
  AlertCircle,
  BarChart3,
  Bell,
  Check,
  Sparkles,
  GitPullRequest,
  KeyRound,
  ListChecks,
  ShieldAlert,
  Lightbulb,
  Megaphone,
  Plug,
  Unplug,
  Radar,
  Settings2,
  Share2,
  ShieldCheck,
  Wrench,
  Wallet,
  type LucideIcon,
} from "lucide-react";
import {
  AppIcon as PanelsTopLeft,
  BackgroundIcon,
  KnowledgeIcon,
} from "@/components/icons/product-icons";

import { AgentAvatar } from "@/components/agents/agent-avatar";
import type { Notification } from "@/lib/notifications-api";
import { cn } from "@/lib/utils";

/** Event identity stays neutral; attention is shown beside the timestamp. */
const KINDS: Record<string, { icon: LucideIcon; attention?: "error" | "warning" }> = {
  run_completed: { icon: Check },
  run_failed: { icon: AlertCircle, attention: "error" },
  approval_requested: { icon: ShieldCheck, attention: "warning" },
  budget_warning: { icon: Wallet, attention: "warning" },
  budget_exceeded: { icon: Wallet, attention: "error" },
  ingestion_completed: { icon: KnowledgeIcon },
  ingestion_failed: { icon: KnowledgeIcon, attention: "error" },
  usage_report: { icon: BarChart3 },
  agent_usage_report: { icon: BarChart3 },
  security_event: { icon: KeyRound },
  configuration_changed: { icon: Settings2 },
  announcement: { icon: Megaphone },
  artifact_version_published: { icon: PanelsTopLeft },
  resource_shared: { icon: Share2 },
  mcp_server_down: { icon: Unplug, attention: "error" },
  mcp_server_recovered: { icon: Plug },
  background_task_paused: { icon: BackgroundIcon, attention: "error" },
  capability_requested: { icon: Wrench, attention: "warning" },
  suggestion: { icon: Lightbulb },
  finding: { icon: Radar, attention: "warning" },
  eval_run_finished: { icon: ListChecks },
  case_generation_finished: { icon: Sparkles },
  improvement_finished: { icon: Sparkles },
  eval_suite_failed: { icon: ListChecks, attention: "error" },
  eval_suite_reevaluated: { icon: ListChecks },
  promotion_overridden: { icon: ShieldAlert, attention: "warning" },
  shared_change_applied: { icon: GitPullRequest, attention: "warning" },
};
const UNKNOWN = { icon: Bell };

/** The agent's identity, or a full-size event icon when there is no agent. */
export function NotificationGlyph({ item }: { item: Notification }) {
  const kind = KINDS[item.event_type] ?? UNKNOWN;
  const Icon = kind.icon;

  if (item.agent) {
    return (
      <span aria-hidden className="size-8 shrink-0">
        <AgentAvatar
          agentId={item.agent.id}
          slug={item.agent.slug}
          hasAvatar={item.agent.has_avatar}
          colorSlot={item.agent.avatar_color}
          size="sm"
          className="h-8 w-8"
        />
      </span>
    );
  }

  return (
    <span
      aria-hidden
      className="bg-foreground/[0.06] text-foreground/75 grid size-8 shrink-0 place-items-center rounded-lg"
    >
      <Icon className="size-[18px]" strokeWidth={1.75} />
    </span>
  );
}

/** A quiet timestamp; only events requiring a response get an extra signal. */
export function NotificationMeta({ item, children }: { item: Notification; children: ReactNode }) {
  const t = useTranslations("notifications");
  const attention = KINDS[item.event_type]?.attention;
  return (
    <span className="text-muted-foreground mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
      {attention && (
        <span className="text-foreground/80 inline-flex items-center gap-1.5">
          <span
            aria-hidden
            className={cn(
              "size-1.5 rounded-full",
              attention === "error" ? "bg-destructive" : "bg-warning",
            )}
          />
          {t("needsAttention")}
          <span aria-hidden className="text-muted-foreground">
            ·
          </span>
        </span>
      )}
      {children}
    </span>
  );
}
