/**
 * @vitest-environment node
 *
 * Route handlers, in the environment they actually run in.
 */
import { describe, expect, it } from "vitest";

import * as adminConversations from "./admin/conversations/route";
import * as adminOrganizations from "./admin/organizations/route";
import * as adminRatingsSummary from "./admin/ratings/summary/route";
import * as adminSettings from "./admin/settings/[[...path]]/route";
import * as adminStats from "./admin/stats/route";
import * as adminSystem from "./admin/system/route";
import * as adminUserDetail from "./admin/users/[userId]/detail/route";
import * as adminUser from "./admin/users/[userId]/route";
import * as adminUsers from "./admin/users/route";
import * as agent from "./agent/[[...path]]/route";
import * as agents from "./agents/[[...path]]/route";
import * as approvals from "./approvals/[[...path]]/route";
import * as audit from "./audit/[[...path]]/route";
import * as catalog from "./catalog/[[...path]]/route";
import * as channels from "./channels/[[...path]]/route";
import * as context from "./context/[[...path]]/route";
import * as conversations from "./conversations/[[...path]]/route";
import * as kb from "./kb/[[...path]]/route";
import * as mcpConnections from "./mcp-connections/[[...path]]/route";
import * as memory from "./memory/[[...path]]/route";
import * as channelLink from "./me/channel-link/[[...path]]/route";
import * as permissions from "./me/permissions/route";
import * as dashboardLayout from "./me/dashboard-layout/route";
import * as dashboardPresets from "./me/dashboard-layout/presets/route";
import * as dashboardPreset from "./me/dashboard-layout/presets/[presetId]/route";
import * as myMcpConnections from "./me/mcp-connections/route";
import * as myMcpConnection from "./me/mcp-connections/[id]/route";
import * as myMcpConnectionTest from "./me/mcp-connections/[id]/test/route";
import * as mcpOauthStart from "./me/mcp-connections/oauth/start/route";
import * as slashCommands from "./me/slash-commands/[[...path]]/route";
import * as orgs from "./orgs/route";
import * as org from "./orgs/[id]/route";
import * as orgInvitations from "./orgs/[id]/invitations/route";
import * as orgInvitation from "./orgs/[id]/invitations/[invitationId]/route";
import * as orgMembers from "./orgs/[id]/members/route";
import * as orgMember from "./orgs/[id]/members/[userId]/route";
import * as providers from "./providers/[[...path]]/route";
import * as rag from "./rag/[[...path]]/route";
import * as ratings from "./ratings/[[...path]]/route";
import * as roles from "./roles/[[...path]]/route";
import * as runs from "./runs/[[...path]]/route";
import * as triggerTemplates from "./trigger-templates/[[...path]]/route";
import * as sandboxConnections from "./sandbox-connections/[[...path]]/route";
import * as sandboxWorkspaces from "./sandbox-workspaces/[[...path]]/route";
import * as secrets from "./secrets/[[...path]]/route";
import * as sessions from "./sessions/[[...path]]/route";
import * as skillChanges from "./skill-changes/[[...path]]/route";
import * as skills from "./skills/[[...path]]/route";
import * as spend from "./spend/[[...path]]/route";
import * as stats from "./stats/[[...path]]/route";
import * as triggerPortals from "./trigger-portals/[[...path]]/route";
import * as triggers from "./triggers/[[...path]]/route";
import * as users from "./users/[userId]/route";

/**
 * Every mount of the shared forwarder.
 *
 * What the forwarder *does* is asserted in `platform-proxy.test.ts`; what is
 * asserted here is that each mount exports the five verbs Next looks for. A
 * route file missing one answers 405 for that method, and nothing in a type
 * check or a page render says so - the symptom is a delete button that does
 * nothing, on one page only.
 */
const MOUNTED: [string, Record<string, unknown>][] = [
  ["admin/conversations", adminConversations],
  ["admin/organizations", adminOrganizations],
  ["admin/ratings/summary", adminRatingsSummary],
  ["admin/settings", adminSettings],
  ["admin/stats", adminStats],
  ["admin/system", adminSystem],
  ["admin/users", adminUsers],
  ["admin/users/[userId]", adminUser],
  ["admin/users/[userId]/detail", adminUserDetail],
  ["agent", agent],
  ["agents", agents],
  ["approvals", approvals],
  ["audit", audit],
  ["catalog", catalog],
  ["channels", channels],
  ["context", context],
  ["conversations", conversations],
  ["kb", kb],
  ["mcp-connections", mcpConnections],
  ["memory", memory],
  ["me/channel-link", channelLink],
  ["me/mcp-connections", myMcpConnections],
  ["me/mcp-connections/[id]", myMcpConnection],
  ["me/mcp-connections/[id]/test", myMcpConnectionTest],
  ["me/mcp-connections/oauth/start", mcpOauthStart],
  ["me/slash-commands", slashCommands],
  ["orgs", orgs],
  ["orgs/[id]", org],
  ["orgs/[id]/invitations", orgInvitations],
  ["orgs/[id]/invitations/[invitationId]", orgInvitation],
  ["orgs/[id]/members", orgMembers],
  ["orgs/[id]/members/[userId]", orgMember],
  ["providers", providers],
  ["rag", rag],
  ["ratings", ratings],
  ["roles", roles],
  ["runs", runs],
  ["sandbox-connections", sandboxConnections],
  ["sandbox-workspaces", sandboxWorkspaces],
  ["trigger-templates", triggerTemplates],
  ["secrets", secrets],
  ["sessions", sessions],
  ["skill-changes", skillChanges],
  ["skills", skills],
  ["spend", spend],
  ["stats", stats],
  ["trigger-portals", triggerPortals],
  ["triggers", triggers],
  ["users/[userId]", users],
  ["me/permissions", permissions],
  ["me/dashboard-layout", dashboardLayout],
  ["me/dashboard-layout/presets", dashboardPresets],
  ["me/dashboard-layout/presets/[presetId]", dashboardPreset],
];

const VERBS = ["GET", "POST", "PUT", "PATCH", "DELETE"] as const;

describe("the proxied route mounts", () => {
  it.each(MOUNTED)("%s handles every verb", (_name, module) => {
    for (const verb of VERBS) {
      expect(typeof module[verb], verb).toBe("function");
    }
  });

  it("mounts one forwarder per file rather than sharing an instance", () => {
    // Each `platformProxy()` call closes over nothing but the request, so two
    // mounts are independent - and a shared instance would be a shared
    // handler with a path taken from whichever request arrived first.
    expect(agents.GET).not.toBe(runs.GET);
  });

  it("refuses an unauthenticated request at every mount", async () => {
    // The gate is the forwarder's, but a mount that somehow bypassed it would be
    // an open door to that whole endpoint family.
    const { NextRequest } = await import("next/server");

    for (const [name, module] of MOUNTED) {
      const handler = module.GET as (request: unknown) => Promise<Response>;
      const response = await handler(new NextRequest(`http://localhost:3000/api/${name}`));

      expect(response.status, name).toBe(401);
    }
  });
});
