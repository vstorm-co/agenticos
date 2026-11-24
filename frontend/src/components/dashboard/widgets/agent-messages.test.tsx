import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TooltipProvider } from "@/components/ui";
import type { AgentMessageThreadRead } from "@/types/agent-messages";
import { AgentMessagesWidget } from "./agent-messages";

const useThreads = vi.fn();
vi.mock("@/hooks", () => ({
  useAgentMessageThreads: (...args: unknown[]) => useThreads(...args),
}));
vi.mock("@/lib/utils", async (original) => ({
  ...(await original<typeof import("@/lib/utils")>()),
  timeAgo: (value: string) => `at ${value}`,
}));

function thread(
  index: number,
  overrides: Partial<AgentMessageThreadRead> = {},
): AgentMessageThreadRead {
  return {
    id: `thread-${index}`,
    agent_a: { id: `a-${index}`, slug: `first-${index}`, name: `First ${index}` },
    agent_b: { id: `b-${index}`, slug: `second-${index}`, name: `Second ${index}` },
    last_message_at: "2026-11-14T08:00:00Z",
    last_message: {
      sender_agent_slug: `first-${index}`,
      body: `Review ${index}`,
      created_at: "2026-11-14T08:00:00Z",
    },
    unread: true,
    created_at: "2026-11-14T07:00:00Z",
    updated_at: "2026-11-14T09:00:00Z",
    ...overrides,
  };
}

function widget() {
  return render(
    <TooltipProvider>
      <AgentMessagesWidget
        title="Agent messages"
        hint="Unread conversations between agents"
        period={{ preset: "30d", from: "2026-10-15", to: "2026-11-14" }}
        seeAll="/agent-messages"
      />
    </TooltipProvider>,
  );
}

describe("AgentMessagesWidget", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useThreads.mockReturnValue({ threads: [], isLoading: false, error: null, refetch: vi.fn() });
  });

  it("shows the first five unread threads in server order with their message previews", () => {
    useThreads.mockReturnValue({
      threads: [
        thread(0, { unread: false }),
        ...Array.from({ length: 6 }, (_, index) => thread(index + 1)),
      ],
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    });
    widget();
    expect(useThreads).toHaveBeenCalledWith(0, 20);
    const rows = screen.getAllByRole("listitem");
    expect(rows).toHaveLength(5);
    rows.forEach((row, index) => {
      const link = within(row).getByRole("link");
      expect(link).toHaveAttribute("href", "/agent-messages");
      expect(link).toHaveTextContent(`First ${index + 1}`);
      expect(link).toHaveTextContent(`Second ${index + 1}`);
      expect(link).toHaveTextContent(`Review ${index + 1}`);
      expect(link).toHaveTextContent("at 2026-11-14T08:00:00Z");
    });
    expect(screen.queryByText(/First 0/)).not.toBeInTheDocument();
    expect(screen.queryByText(/First 6/)).not.toBeInTheDocument();
  });

  it("uses the thread's update time when it has no last message yet", () => {
    useThreads.mockReturnValue({
      threads: [thread(1, { last_message: null, last_message_at: null })],
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    });
    widget();
    const row = screen.getByRole("listitem");
    expect(row).toHaveTextContent("at 2026-11-14T09:00:00Z");
    expect(row).toHaveTextContent("No messages yet.");
    expect(row).not.toHaveTextContent("Review 1");
    expect(within(row).getByRole("link")).toHaveTextContent("First 1");
  });

  it("does not offer already-read threads as unread work", () => {
    useThreads.mockReturnValue({
      threads: [thread(1, { unread: false })],
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    });
    widget();
    expect(screen.queryByRole("list")).not.toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.queryByText(/First 1/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /retry/i })).not.toBeInTheDocument();
  });

  it("offers retry after a failed read instead of presenting cached threads as current", async () => {
    const refetch = vi.fn();
    useThreads.mockReturnValue({
      threads: [thread(1)],
      isLoading: false,
      error: new Error("502"),
      refetch,
    });
    widget();
    expect(screen.queryByRole("list")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(refetch).toHaveBeenCalledOnce();
  });

  it("shows loading before it decides whether the inbox is empty", () => {
    useThreads.mockReturnValue({ threads: [], isLoading: true, error: null, refetch: vi.fn() });
    widget();
    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.queryByRole("list")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /retry/i })).not.toBeInTheDocument();
  });
});
