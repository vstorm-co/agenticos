import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeEach, expect, it, vi } from "vitest";

import { ActionConsentsDialog } from "@/components/triggers/action-consents-dialog";
import { useMcpConnections } from "./use-mcp-connections";
import { useOrgMcpConnections } from "./use-org-mcp-connections";
import { apiClient } from "@/lib/api-client";
import type { Trigger } from "@/types/triggers";

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return { ...actual, apiClient: { get: vi.fn(), post: vi.fn(), put: vi.fn() } };
});

const trigger: Trigger = {
  id: "t1",
  agent_id: "a1",
  agent_name: "Test agent",
  name: "Review test",
  created_by_user_id: "creator",
  is_active: false,
  can_manage: true,
  environment_id: null,
  runs_as_creator: true,
  trigger_type: "schedule",
  schedule_kind: "interval",
  interval_seconds: 900,
  cron_expression: null,
  time_zone: null,
  overlap: "skip",
  event_source: null,
  event_config: {},
  prompt: "Test",
  next_fire_at: null,
  last_fired_at: null,
  last_run_id: null,
  conversation_id: null,
  webhook_url: null,
  created_at: null,
  updated_at: null,
  setup_required: true,
};

function ReviewFlow({ scope }: { scope: "personal" | "organization" }) {
  const personal = useMcpConnections();
  const organization = useOrgMcpConnections();
  const connections = scope === "personal" ? personal : organization;
  const [reviewing, setReviewing] = useState(true);
  const [checked, setChecked] = useState(false);
  return (
    <>
      <button
        onClick={async () => {
          await connections.test("c1");
          setChecked(true);
        }}
      >
        Check connection
      </button>
      {checked && <p>Connection checked</p>}
      <button onClick={() => setReviewing(true)}>Review again</button>
      {reviewing && (
        <ActionConsentsDialog
          trigger={trigger}
          onClose={() => setReviewing(false)}
          onSaved={async () => {}}
        />
      )}
    </>
  );
}

beforeEach(() => vi.clearAllMocks());

it.each([
  ["personal", true],
  ["organization", true],
  ["personal", false],
  ["organization", false],
] as const)("reopens the current review after a %s probe (healthy: %s)", async (scope, healthy) => {
  let repaired = false;
  vi.mocked(apiClient.get).mockImplementation(async (path) => {
    if (path.endsWith("/sources"))
      return {
        current: false,
        review_token: repaired ? "new-sources" : "old-sources",
        version_id: "v1",
        resources: [],
        accounts: [],
        unavailable_sources: repaired ? [] : ["notion"],
      };
    if (path.endsWith("/action-consents"))
      return {
        can_waive: true,
        review_token: repaired ? "new-actions" : "old-actions",
        items: [],
        unavailable_sources: repaired ? [] : ["notion"],
      };
    if (path.endsWith("mcp-connections")) return { items: [], total: 0 };
    throw new Error(`Unexpected GET ${path}`);
  });
  vi.mocked(apiClient.post).mockImplementation(async () => {
    repaired = healthy;
    return { ok: healthy, error: healthy ? null : "offline", tools: [] };
  });
  // The user returns before the ordinary freshness window expires. Only a
  // dependency invalidation can make this inactive review fetch again.
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  render(
    <QueryClientProvider client={client}>
      <ReviewFlow scope={scope} />
    </QueryClientProvider>,
  );
  await screen.findByText("Reconnect or inspect these sources first: notion");
  expect(screen.getByRole("button", { name: "Enable routine" })).toBeDisabled();
  await userEvent.click(screen.getByRole("button", { name: "Finish later" }));
  await userEvent.click(screen.getByRole("button", { name: "Check connection" }));
  await screen.findByText("Connection checked");
  expect(apiClient.post).toHaveBeenCalledWith(
    scope === "personal" ? "/me/mcp-connections/c1/test" : "/mcp-connections/c1/test",
  );
  await userEvent.click(screen.getByRole("button", { name: "Review again" }));
  await waitFor(() => {
    expect(
      vi.mocked(apiClient.get).mock.calls.filter(([path]) => path.endsWith("/sources")),
    ).toHaveLength(2);
    expect(
      vi.mocked(apiClient.get).mock.calls.filter(([path]) => path.endsWith("/action-consents")),
    ).toHaveLength(2);
  });
  const enable = screen.getByRole("button", { name: "Enable routine" });
  if (healthy) {
    await waitFor(() => expect(enable).toBeEnabled());
    expect(screen.queryByText("Reconnect or inspect these sources first: notion")).toBeNull();
  } else {
    expect(enable).toBeDisabled();
    expect(screen.getByText("Reconnect or inspect these sources first: notion")).toBeVisible();
  }
  expect(apiClient.put).not.toHaveBeenCalled();
});
