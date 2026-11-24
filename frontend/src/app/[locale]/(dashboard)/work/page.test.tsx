import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ConversationTask } from "@/hooks/use-conversation-tasks";
import WorkPage from "./page";
const state = vi.hoisted(() => ({ can: true, stop: vi.fn() }));
const task = (id: string, status: ConversationTask["status"]): ConversationTask => ({
  id,
  title: `Task ${id}`,
  status,
  conversation_id: `chat/${id}`,
  source_conversation_id: "source",
  agent_id: "agent",
  delivery: "pending",
  run_id: null,
  return_run_id: null,
  outcome: status === "completed" ? "Research result" : null,
  created_at: "2026-11-04T12:00:00Z",
});
vi.mock("@/hooks/use-permissions", () => ({ usePermissions: () => ({ can: () => state.can }) }));
vi.mock("@/hooks/use-conversation-tasks", async (original) => ({
  ...(await original<typeof import("@/hooks/use-conversation-tasks")>()),
  useConversationTasks: () => ({
    data: [task("active", "running"), task("done", "completed")],
    isPending: false,
    error: null,
    stop: { isPending: false, mutate: state.stop },
  }),
}));
beforeEach(() => {
  state.can = true;
  state.stop.mockClear();
});
afterEach(() => vi.restoreAllMocks());

describe("WorkPage", () => {
  it("measures one shared selection marker while keeping task counts and pressed state", async () => {
    vi.spyOn(HTMLElement.prototype, "offsetWidth", "get").mockReturnValue(96);
    vi.spyOn(HTMLElement.prototype, "offsetLeft", "get").mockImplementation(function (
      this: HTMLElement,
    ) {
      return this.textContent?.startsWith("History") ? 120 : 0;
    });
    render(<WorkPage />);
    const strip = screen.getByRole("group", { name: "Background work" });
    const active = screen.getByRole("button", { name: /In progress/ });
    const history = screen.getByRole("button", { name: /History/ });
    expect(strip).toHaveAttribute("data-tab-indicator", "line");
    expect(strip).toHaveAttribute("data-indicator-ready");
    expect(strip.style.getPropertyValue("--tab-x")).toBe("0px");
    expect(strip.style.getPropertyValue("--tab-width")).toBe("96px");
    expect(active).toHaveAttribute("aria-pressed", "true");
    expect(active).toHaveTextContent("1");
    expect(history).toHaveTextContent("1");
    fireEvent.click(history);
    await waitFor(() => expect(strip.style.getPropertyValue("--tab-x")).toBe("120px"));
    expect(history).toHaveAttribute("aria-pressed", "true");
    expect(active).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByText("Research result")).toBeInTheDocument();
  });
  it("separates ongoing tasks from results while preserving stop and conversation links", () => {
    render(<WorkPage />);
    expect(screen.queryByRole("button", { name: "New task" })).toBeNull();
    expect(screen.getByRole("link", { name: "Task active" })).toHaveAttribute(
      "href",
      "/chat?id=chat%2Factive",
    );
    expect(screen.queryByText("Task done")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Stop.*Task active/ }));
    expect(state.stop).toHaveBeenCalledWith("active");
    fireEvent.click(screen.getByRole("button", { name: /History/ }));
    expect(screen.getByText("Research result")).toBeInTheDocument();
    expect(screen.queryByText("Task active")).toBeNull();
  });
  it("hides routine management from members without agent access", () => {
    state.can = false;
    render(<WorkPage />);
    expect(screen.queryByRole("link", { name: /Routines/ })).toBeNull();
  });
});
