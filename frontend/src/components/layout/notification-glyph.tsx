import {
  AlertCircle,
  BarChart3,
  Bell,
  CheckCircle2,
  Database,
  KeyRound,
  Megaphone,
  PanelsTopLeft,
  PauseCircle,
  Plug,
  PlugZap,
  Settings2,
  Share2,
  ShieldCheck,
  Wallet,
  type LucideIcon,
} from "lucide-react";

import { AgentAvatar } from "@/components/agents/agent-avatar";
import type { Notification } from "@/lib/notifications-api";
import { cn } from "@/lib/utils";

/** The neutral tile; a kind only takes a colour when the colour is the news. */
const NEUTRAL = "bg-muted text-foreground";
const GOOD = "bg-success/10 text-success";
const BAD = "bg-destructive/10 text-destructive";
const HELD = "bg-warning/10 text-warning";

/** What each kind of event looks like: its icon, and the tint that says how it went. */
const KINDS: Record<string, { icon: LucideIcon; tone: string }> = {
  run_completed: { icon: CheckCircle2, tone: GOOD },
  run_failed: { icon: AlertCircle, tone: BAD },
  approval_requested: { icon: ShieldCheck, tone: HELD },
  budget_warning: { icon: Wallet, tone: HELD },
  budget_exceeded: { icon: Wallet, tone: BAD },
  ingestion_completed: { icon: Database, tone: NEUTRAL },
  ingestion_failed: { icon: Database, tone: BAD },
  usage_report: { icon: BarChart3, tone: NEUTRAL },
  agent_usage_report: { icon: BarChart3, tone: NEUTRAL },
  // Neutral: most of these are a secret created or a key issued, and painting
  // every one red teaches the reader to stop looking at the red ones.
  security_event: { icon: KeyRound, tone: NEUTRAL },
  configuration_changed: { icon: Settings2, tone: NEUTRAL },
  announcement: { icon: Megaphone, tone: NEUTRAL },
  artifact_version_published: { icon: PanelsTopLeft, tone: NEUTRAL },
  resource_shared: { icon: Share2, tone: NEUTRAL },
  mcp_server_down: { icon: PlugZap, tone: BAD },
  mcp_server_recovered: { icon: Plug, tone: GOOD },
  background_task_paused: { icon: PauseCircle, tone: BAD },
};

/** A kind this console has not met yet: a bell, rather than nothing. */
const UNKNOWN = { icon: Bell, tone: NEUTRAL };

/**
 * What a notification is about, at a glance: the agent's face with the event
 * as a badge on it when the row is about an agent, and the event's own icon
 * otherwise.
 *
 * A face first because "Support's run finished" and "Billing's run failed" are
 * told apart by whose they are before what happened to them - the same way a
 * chat list is read by its avatars.
 */
export function NotificationGlyph({ item }: { item: Notification }) {
  const kind = KINDS[item.event_type] ?? UNKNOWN;
  const Icon = kind.icon;

  if (item.agent) {
    return (
      <span aria-hidden className="relative h-8 w-8 shrink-0">
        <AgentAvatar
          agentId={item.agent.id}
          slug={item.agent.slug}
          hasAvatar={item.agent.has_avatar}
          colorSlot={item.agent.avatar_color}
          size="sm"
          className="h-8 w-8"
        />
        {/* A solid disc under the tint: the tints are translucent, and over a
            face they would let it show through the icon. */}
        <span className="bg-popover ring-popover absolute -right-1 -bottom-1 rounded-full ring-2">
          <span className={cn("grid h-4 w-4 place-items-center rounded-full", kind.tone)}>
            <Icon className="h-2.5 w-2.5" />
          </span>
        </span>
      </span>
    );
  }

  return (
    <span
      aria-hidden
      className={cn("grid h-8 w-8 shrink-0 place-items-center rounded-lg", kind.tone)}
    >
      <Icon className="h-4 w-4" />
    </span>
  );
}
