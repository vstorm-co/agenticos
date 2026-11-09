import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import type { ToolCall } from "@/types";
import type { Trigger } from "@/types/triggers";
import { RoutineResult, writtenRoutines } from "./routine";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
vi.mock("@/components/triggers/trigger-row", () => ({
  TriggerRow: ({ trigger }: { trigger: Trigger }) => (
    <div>
      {trigger.name}
      {trigger.can_manage && <button>Manage</button>}
    </div>
  ),
}));

const ID = "00000000-0000-4000-8000-000000000001";
const AGENT = "00000000-0000-4000-8000-000000000002";
const reference = { id: ID, agentId: AGENT };
const saved = { id: ID, agent_id: AGENT, trigger_type: "schedule", name: "Recorded name" };

function call(overrides: Partial<ToolCall> = {}): ToolCall {
  return {
    id: "call",
    name: "agenticos_create_routine",
    args: {},
    result: JSON.stringify(saved),
    status: "completed",
    ...overrides,
  };
}

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <RoutineResult routine={reference} />
    </QueryClientProvider>,
  );
}

describe("routine results", () => {
  beforeEach(() => vi.clearAllMocks());

  it("deduplicates successful platform writes and refuses other results", () => {
    expect(
      writtenRoutines([call(), call({ name: "agenticos_update_routine", result: saved })]),
    ).toEqual([reference]);
    for (const item of [
      call({ name: "other_create_routine" }),
      call({ status: "error" }),
      call({ result: "Forbidden" }),
      call({ result: null }),
      call({ result: "[]" }),
      call({ result: { ...saved, id: "invalid" } }),
      call({ result: { ...saved, agent_id: "invalid" } }),
      call({ result: { ...saved, trigger_type: "unknown" } }),
    ])
      expect(writtenRoutines([item])).toEqual([]);
  });

  it("loads current authorized state instead of trusting recorded names or management rights", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      items: [
        {
          ...saved,
          name: "Current name",
          is_active: true,
          can_manage: false,
          next_fire_at: "2026-11-03T09:00:00Z",
        },
      ],
      total: 1,
    });
    show();
    expect(await screen.findByText("Current name")).toBeVisible();
    expect(screen.queryByText("Recorded name")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Manage" })).not.toBeInTheDocument();
    expect(screen.getByText(/Next activation:/)).toBeVisible();
  });

  it("shows a retryable failure rather than claiming the routine was removed", async () => {
    vi.mocked(apiClient.get).mockRejectedValue(new Error("offline"));
    show();
    expect(await screen.findByRole("alert")).toHaveTextContent("could not be loaded");
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("This routine is no longer available.")).toBeVisible();
  });

  it("shows loading while the request is pending", () => {
    vi.mocked(apiClient.get).mockReturnValue(new Promise(() => {}));
    show();
    expect(screen.getByRole("status")).toHaveTextContent("Loading routine");
  });
});

it("keeps trusted platform cards and refuses a generic external routine", () => {
  expect(writtenRoutines([call({ presentation_kind: "platform" })])).toEqual([reference]);
  expect(writtenRoutines([call({ presentation_kind: "generic" })])).toEqual([]);
});
