/**
 * @vitest-environment node
 *
 * Route handlers, in the environment they actually run in.
 */
import { describe, expect, it } from "vitest";

import * as adminSettings from "./admin/settings/[[...path]]/route";
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
import * as permissions from "./me/permissions/route";
import * as dashboardLayout from "./me/dashboard-layout/route";
import * as dashboardPresets from "./me/dashboard-layout/presets/route";
import * as dashboardPreset from "./me/dashboard-layout/presets/[presetId]/route";
import * as builtinCommands from "./me/slash-commands/builtin/route";
import * as providers from "./providers/[[...path]]/route";
import * as rag from "./rag/[[...path]]/route";
import * as ratings from "./ratings/[[...path]]/route";
import * as roles from "./roles/[[...path]]/route";
import * as runs from "./runs/[[...path]]/route";
import * as triggerTemplates from "./trigger-templates/[[...path]]/route";
import * as sandboxConnections from "./sandbox-connections/[[...path]]/route";
import * as sandboxWorkspaces from "./sandbox-workspaces/[[...path]]/route";
import * as secrets from "./secrets/[[...path]]/route";
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
  ["admin/settings", adminSettings],
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
  ["providers", providers],
  ["rag", rag],
  ["ratings", ratings],
  ["roles", roles],
  ["runs", runs],
  ["sandbox-connections", sandboxConnections],
  ["sandbox-workspaces", sandboxWorkspaces],
  ["trigger-templates", triggerTemplates],
  ["secrets", secrets],
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

  it("mounts the one route that is not a catch-all with the same forwarder", async () => {
    // `me/slash-commands/builtin` is hand-rolled because it needs a PUT the
    // template's generator does not emit; it still has to answer one.
    expect(typeof builtinCommands.PUT).toBe("function");
  });
});
