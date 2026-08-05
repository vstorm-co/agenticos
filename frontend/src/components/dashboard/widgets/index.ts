/**
 * Widget id to component. The registry (src/lib/dashboard/registry.ts) holds
 * the decision data - gates, spans, destinations - and stays JSX-free so the
 * coverage gate can hold it to 100%; this map holds the React halves. The
 * page zips the two, and a registry id without a component here is a build
 * error at the page's lookup, not a silently blank cell.
 */

import type { ComponentType } from "react";

import type { WidgetId } from "@/lib/dashboard/registry";
import { ActiveUsersWidget } from "./active-users";
import { AgentsAdoptionWidget } from "./agents-adoption";
import { ApprovalsWidget } from "./approvals";
import { BudgetHeadroomWidget } from "./budget-headroom";
import { ConversationsWidget } from "./conversations";
import { HealthWidget } from "./health";
import { KnowledgeFreshnessWidget } from "./knowledge-freshness";
import { LatencyWidget } from "./latency";
import { McpHealthWidget } from "./mcp-health";
import { MembersWidget } from "./members";
import { ModelMixWidget } from "./model-mix";
import { MyActivityWidget } from "./my-activity";
import { MyAgentsWidget } from "./my-agents";
import { MyQualityWidget } from "./my-quality";
import { MyTopAgentsWidget } from "./my-top-agents";
import { OrgRatingsWidget } from "./org-ratings";
import { OutcomesWidget } from "./outcomes";
import { PlatformWidget } from "./platform";
import { PlatformRatingsWidget } from "./platform-ratings";
import { RecentFailuresWidget } from "./recent-failures";
import { RunsWidget } from "./runs";
import { SharedWithYouWidget } from "./shared-with-you";
import { SpendWidget } from "./spend";
import { SurfacesWidget } from "./surfaces";
import { TopOrgsWidget } from "./top-orgs";
import { VersionCompareWidget } from "./version-compare";
import type { DashboardWidgetProps } from "./types";

export const WIDGET_COMPONENTS: Record<WidgetId, ComponentType<DashboardWidgetProps>> = {
  platform: PlatformWidget,
  health: HealthWidget,
  "top-orgs": TopOrgsWidget,
  "platform-ratings": PlatformRatingsWidget,
  runs: RunsWidget,
  outcomes: OutcomesWidget,
  surfaces: SurfacesWidget,
  agents: AgentsAdoptionWidget,
  latency: LatencyWidget,
  "active-users": ActiveUsersWidget,
  spend: SpendWidget,
  "model-mix": ModelMixWidget,
  "version-compare": VersionCompareWidget,
  approvals: ApprovalsWidget,
  "recent-failures": RecentFailuresWidget,
  "budget-headroom": BudgetHeadroomWidget,
  "mcp-health": McpHealthWidget,
  "knowledge-freshness": KnowledgeFreshnessWidget,
  members: MembersWidget,
  "org-ratings": OrgRatingsWidget,
  "my-agents": MyAgentsWidget,
  conversations: ConversationsWidget,
  "my-activity": MyActivityWidget,
  "my-top-agents": MyTopAgentsWidget,
  "my-quality": MyQualityWidget,
  "shared-with-you": SharedWithYouWidget,
};

export type { DashboardWidgetProps } from "./types";
