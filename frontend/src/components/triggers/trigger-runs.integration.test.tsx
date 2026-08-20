import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TriggerRow } from "./trigger-row";
import { apiClient } from "@/lib/api-client";
import { useTriggers } from "@/hooks/use-triggers";
import type { ChatMessage } from "@/types";
import type { Trigger } from "@/types/triggers";

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return {
    ...actual,
    apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

// The chat renderer is exercised by its own tests; here it is stubbed so what
// this asserts is the run-log view's own job - which turns it hands over, and
// whether it appends the just-sent prompt and a waiting placeholder.
vi.mock("@/components/chat/message-list", () => ({
  MessageList: ({ messages }: { messages: ChatMessage[] }) => (
    <ul>
      {messages.map((m) => (
        <li key={m.id} data-streaming={m.isStreaming ? "true" : "false"}>
          {m.isStreaming ? <span role="status">waiting</span> : m.content}
        </li>
      ))}
    </ul>
  ),
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function trigger(overrides: Partial<Trigger> = {}): Trigger {
  return {
    id: "t1",
    agent_id: "a1",
    agent_name: "Digest bot",
    name: null,
    created_by_user_id: null,
    is_active: true,
    can_manage: true,
    environment_id: null,
    trigger_type: "schedule",
    schedule_kind: "interval",
    interval_seconds: 900,
    cron_expression: null,
    event_source: null,
    event_config: {},
    prompt: "Summarise the day",
    next_fire_at: null,
    last_fired_at: null,
    last_run_id: null,
    conversation_id: "c1",
    webhook_url: null,
    created_at: null,
    updated_at: null,
    ...overrides,
  };
}

const transcript = (
  items: { id: string; role: string; content: string; created_at?: string }[],
) => ({
  run_id: "r1",
  conversation_id: "c1",
  items,
  total: items.length,
});

// A moment safely after "Run now" was pressed, so a reply carrying it counts as
// the fresh one that ends the wait.
const AFTER_NOW = () => new Date(Date.now() + 3_600_000).toISOString();

function serveGets(handler: (path: string) => unknown) {
  vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
    if (path === "/agents") return { items: [], total: 0 };
    return handler(path);
  });
}

describe("TriggerRow run-log view", () => {
  beforeEach(() => vi.clearAllMocks());

  it("says there are no messages yet for a trigger that has never fired", async () => {
    serveGets(() => {
      throw new Error("no transcript should be read for a never-fired trigger");
    });
    render(<TriggerRow trigger={trigger()} />, { wrapper });

    await userEvent.click(screen.getByRole("button", { name: "See what this trigger has done" }));

    expect(await screen.findByText("No messages yet")).toBeVisible();
    expect(apiClient.get).not.toHaveBeenCalledWith("/runs/r1/transcript", expect.anything());
  });

  it("opens the run-log conversation when the row is clicked", async () => {
    serveGets((path) => {
      if (path === "/runs/r1/transcript")
        return {
          run_id: "r1",
          // A log whose conversation the read could not name still renders its turns.
          conversation_id: null,
          items: [
            { id: "m1", role: "user", content: "Summarise the day" },
            { id: "m2", role: "assistant", content: "Here is the summary" },
          ],
          total: 2,
        };
      throw new Error(`unexpected GET ${path}`);
    });
    // A named trigger titles the drawer by its name.
    render(<TriggerRow trigger={trigger({ last_run_id: "r1", name: "Morning digest" })} />, {
      wrapper,
    });

    await userEvent.click(screen.getByRole("button", { name: "See what this trigger has done" }));

    const drawer = within(await screen.findByRole("dialog"));
    expect(drawer.getByText("Morning digest")).toBeVisible();
    expect(drawer.getByText("Here is the summary")).toBeVisible();
  });

  it("keeps the action buttons working without opening the view", async () => {
    vi.mocked(apiClient.patch).mockResolvedValue(trigger({ is_active: false }));
    serveGets(() => ({}));
    render(<TriggerRow trigger={trigger({ last_run_id: "r1" })} />, { wrapper });

    await userEvent.click(screen.getByRole("button", { name: "Pause" }));

    await waitFor(() => expect(apiClient.patch).toHaveBeenCalled());
    expect(screen.queryByText("Trigger runs")).toBeNull();
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("opens the view showing the prompt and a waiting animation after Run now", async () => {
    vi.mocked(apiClient.post).mockResolvedValue(trigger());
    serveGets(() => ({}));
    render(<TriggerRow trigger={trigger()} />, { wrapper });

    await userEvent.click(screen.getByRole("button", { name: "Run now" }));

    // The prompt just sent, and the pending-agent placeholder beneath it -
    // scoped to the drawer, since the row itself also shows the prompt.
    const drawer = within(await screen.findByRole("dialog"));
    expect(await drawer.findByText("Summarise the day")).toBeVisible();
    expect(drawer.getByRole("status")).toBeVisible();
  });

  it("shows the existing log plus the waiting turn when re-firing a trigger", async () => {
    vi.mocked(apiClient.post).mockResolvedValue(trigger({ last_run_id: "r1" }));
    serveGets((path) => {
      if (path === "/runs/r1/transcript")
        return transcript([{ id: "m1", role: "assistant", content: "Earlier answer" }]);
      throw new Error(`unexpected GET ${path}`);
    });
    render(<TriggerRow trigger={trigger({ last_run_id: "r1" })} />, { wrapper });

    await userEvent.click(screen.getByRole("button", { name: "Run now" }));

    expect(await screen.findByText("Earlier answer")).toBeVisible();
    expect(screen.getByRole("status")).toBeVisible();
  });

  it("keeps polling a never-fired trigger until its first run acquires an id", async () => {
    // The transcript query is disabled while last_run_id is null, so the
    // trigger itself is what must be re-read - through a mounted list query,
    // as the panel mounts it, or the invalidation would have nothing to
    // refetch and the drawer would spin forever on its optimistic waiting.
    let listCalls = 0;
    vi.mocked(apiClient.post).mockResolvedValue(trigger());
    serveGets((path) => {
      if (path === "/agents/a1/triggers") {
        listCalls += 1;
        return { items: [trigger(listCalls >= 3 ? { last_run_id: "r1" } : {})], total: 1 };
      }
      if (path === "/runs/r1/transcript")
        return transcript([
          { id: "m1", role: "assistant", content: "Done it", created_at: AFTER_NOW() },
        ]);
      throw new Error(`unexpected GET ${path}`);
    });
    function Harness() {
      const { triggers } = useTriggers("a1");
      const row = triggers[0];
      return row ? <TriggerRow trigger={row} /> : null;
    }
    render(<Harness />, { wrapper });

    await userEvent.click(await screen.findByRole("button", { name: "Run now" }));
    const drawer = within(await screen.findByRole("dialog"));

    // One poll later the id has landed, the transcript answers, and the
    // fresh reply replaces the optimistic placeholder.
    expect(await drawer.findByText("Done it", undefined, { timeout: 10_000 })).toBeVisible();
    expect(drawer.queryByRole("status")).toBeNull();
    expect(listCalls).toBeGreaterThanOrEqual(3);
  }, 15_000);

  it("closes the drawer from its close button", async () => {
    serveGets(() => ({}));
    // No name and no agent name, so the drawer falls back to its generic title.
    render(<TriggerRow trigger={trigger({ name: null, agent_name: null })} />, { wrapper });

    await userEvent.click(screen.getByRole("button", { name: "See what this trigger has done" }));
    expect(await screen.findByText("Trigger runs")).toBeVisible();
    expect(await screen.findByText("No messages yet")).toBeVisible();

    await userEvent.click(screen.getByRole("button", { name: "Close" }));

    await waitFor(() => expect(screen.queryByText("No messages yet")).toBeNull());
  });

  it("says a failed read out loud rather than as an empty log", async () => {
    serveGets((path) => {
      if (path === "/runs/r1/transcript") throw new Error("boom");
      throw new Error(`unexpected GET ${path}`);
    });
    render(<TriggerRow trigger={trigger({ last_run_id: "r1" })} />, { wrapper });

    await userEvent.click(screen.getByRole("button", { name: "See what this trigger has done" }));

    expect(await screen.findByText("This trigger's runs could not be read.")).toBeVisible();
  });

  it("drops the waiting animation once a newer run has landed", async () => {
    vi.mocked(apiClient.post).mockResolvedValue(trigger());
    serveGets((path) => {
      if (path === "/runs/r2/transcript")
        return transcript([
          { id: "m1", role: "assistant", content: "Fresh answer", created_at: AFTER_NOW() },
        ]);
      return {};
    });
    const { rerender } = render(<TriggerRow trigger={trigger()} />, { wrapper });

    await userEvent.click(screen.getByRole("button", { name: "Run now" }));
    expect(await screen.findByRole("status")).toBeVisible();

    // The list refetches and the trigger now names the run the fire produced;
    // once its reply is recorded, the waiting turn gives way to what was said.
    rerender(<TriggerRow trigger={trigger({ last_run_id: "r2" })} />);

    expect(await screen.findByText("Fresh answer")).toBeVisible();
    await waitFor(() => expect(screen.queryByRole("status")).toBeNull());
  });
});
