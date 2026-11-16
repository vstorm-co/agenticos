import {
  Bell,
  CircleDollarSign,
  FileCheck2,
  FileText,
  FileX2,
  GitPullRequest,
  Hand,
  ListChecks,
  ShieldAlert,
  Lightbulb,
  Megaphone,
  PieChart,
  Radar,
  ServerCrash,
  ServerCog,
  Share2,
  Sparkles,
  UserRoundCog,
  XCircle,
  type LucideIcon,
} from "lucide-react";
import { WorkflowIcon as Workflow } from "@/components/icons/product-icons";
import type { NotificationChannel } from "@/lib/notification-preferences-api";

interface PreferenceEvent {
  /** The backend's own `NotificationEventType` value. */
  eventType: string;
  /** Catalog key: the name, plus `Trigger` - the same suffix `OPTIONAL_EMAILS`
   * uses, so the three events that reuse those keys need no key of their own. */
  words: string;
  icon: LucideIcon;
  /** Which channels `GET /notifications/preferences` offers for this event -
   * a subset of `["in_app", "email", "push"]`, per Decision 4's togglable-pairs rule. */
  channels: readonly NotificationChannel[];
}

export const CHANNEL_LABEL: Record<NotificationChannel, string> = {
  in_app: "inAppChannel",
  email: "emailChannel",
  push: "pushChannel",
  slack: "slackChannel",
  telegram: "telegramChannel",
  mattermost: "mattermostChannel",
  teams: "teamsChannel",
  sms: "smsChannel",
  imessage: "imessageChannel",
  discord: "discordChannel",
};

export const PREFERENCE_EVENTS: readonly PreferenceEvent[] = [
  {
    eventType: "run_completed",
    words: "prefRunCompleted",
    icon: Bell,
    channels: ["in_app", "email", "push"],
  },
  {
    eventType: "run_failed",
    words: "prefRunFailed",
    icon: XCircle,
    channels: ["in_app", "email", "push"],
  },
  {
    eventType: "artifact_version_published",
    words: "prefArtifactVersionPublished",
    icon: FileText,
    channels: ["in_app", "email", "push"],
  },
  {
    eventType: "resource_shared",
    words: "prefResourceShared",
    icon: Share2,
    channels: ["in_app", "email", "push"],
  },
  {
    eventType: "budget_warning",
    words: "prefBudgetWarning",
    icon: CircleDollarSign,
    channels: ["in_app", "email", "push"],
  },
  {
    eventType: "mcp_server_down",
    words: "prefMcpServerDown",
    icon: ServerCrash,
    channels: ["in_app", "email", "push"],
  },
  {
    eventType: "mcp_server_recovered",
    words: "prefMcpServerRecovered",
    icon: ServerCog,
    channels: ["in_app", "email", "push"],
  },
  {
    eventType: "eval_run_finished",
    words: "prefEvalRunFinished",
    icon: ListChecks,
    channels: ["in_app", "email"],
  },
  {
    eventType: "case_generation_finished",
    words: "prefCaseGenerationFinished",
    icon: Sparkles,
    channels: ["in_app", "email"],
  },
  {
    eventType: "improvement_finished",
    words: "prefImprovementFinished",
    icon: Sparkles,
    channels: ["in_app", "email"],
  },
  {
    eventType: "eval_suite_reevaluated",
    words: "prefSuiteReevaluated",
    icon: ListChecks,
    channels: ["in_app", "email"],
  },
  {
    eventType: "eval_suite_failed",
    words: "prefEvalSuiteFailed",
    icon: ListChecks,
    channels: ["in_app", "email"],
  },
  {
    eventType: "promotion_overridden",
    words: "prefPromotionOverridden",
    icon: ShieldAlert,
    channels: ["in_app", "email"],
  },
  {
    eventType: "shared_change_applied",
    words: "prefSharedChangeApplied",
    icon: GitPullRequest,
    channels: ["in_app", "email"],
  },
  {
    eventType: "ingestion_completed",
    words: "prefIngestionCompleted",
    icon: FileCheck2,
    channels: ["in_app", "email", "push"],
  },
  {
    eventType: "ingestion_failed",
    words: "prefIngestionFailed",
    icon: FileX2,
    channels: ["in_app", "email", "push"],
  },
  // These three reuse `OPTIONAL_EMAILS`' own catalog keys: same event, same
  // name and trigger sentence, just this event's *in-app* channel rather
  // than its email one - `notify_budget_alerts` and friends above already
  // cover email, and `GET /notifications/preferences` never offers it again.
  {
    eventType: "budget_exceeded",
    words: "optionalBudget",
    icon: CircleDollarSign,
    channels: ["in_app", "push"],
  },
  {
    eventType: "approval_requested",
    words: "optionalApprovals",
    icon: Hand,
    channels: ["in_app", "push"],
  },
  {
    eventType: "usage_report",
    words: "optionalUsage",
    icon: PieChart,
    channels: ["in_app", "push"],
  },
  {
    eventType: "agent_usage_report",
    words: "prefAgentUsageReport",
    icon: PieChart,
    channels: ["in_app", "push"],
  },
  {
    eventType: "suggestion",
    words: "prefSuggestion",
    icon: Lightbulb,
    channels: ["in_app", "email", "push"],
  },
  {
    eventType: "finding",
    words: "prefFinding",
    icon: Radar,
    channels: ["in_app", "email", "push"],
  },
  {
    eventType: "capability_requested",
    words: "prefCapabilityRequested",
    icon: Sparkles,
    channels: ["in_app", "email", "push"],
  },
  {
    eventType: "announcement",
    words: "prefAnnouncement",
    icon: Megaphone,
    channels: ["in_app", "email", "push"],
  },
  {
    eventType: "workflow_notification",
    words: "prefWorkflowNotification",
    icon: Workflow,
    channels: ["in_app", "email", "push"],
  },
  {
    eventType: "workflow_log_alert",
    words: "prefWorkflowLogAlert",
    icon: Bell,
    channels: ["in_app", "email", "push"],
  },
  {
    eventType: "artifact_owner_changed",
    words: "prefArtifactOwnerChanged",
    icon: UserRoundCog,
    channels: ["in_app", "email", "push"],
  },
  {
    eventType: "artifact_share_requested",
    words: "prefArtifactShareRequested",
    icon: GitPullRequest,
    channels: ["in_app", "email", "push"],
  },
];
