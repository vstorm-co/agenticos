import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { TooltipProvider } from "@/components/ui";
import { BackgroundTasksWidget } from "./background-tasks";
const env = vi.hoisted(() => ({ state: vi.fn() }));
vi.mock("@/hooks/use-conversation-tasks", () => ({
  useConversationTasks: () => env.state(),
  taskIsActive: () => true,
}));
function view() {
  return render(
    <TooltipProvider>
      <BackgroundTasksWidget
        title="Background topics"
        hint="Delegated work"
        period={{ preset: "30d", from: "2026-10-03", to: "2026-11-03" }}
      />
    </TooltipProvider>,
  );
}
it("shows loading, error, empty, missing-response and active work with its stop action", async () => {
  const retry = vi.fn(),
    stop = vi.fn();
  env.state.mockReturnValue({ isPending: true });
  const current = view();
  env.state.mockReturnValue({ isPending: false, error: new Error("offline"), refetch: retry });
  current.rerender(
    <TooltipProvider>
      <BackgroundTasksWidget
        title="Background topics"
        hint="Delegated work"
        period={{ preset: "30d", from: "2026-10-03", to: "2026-11-03" }}
      />
    </TooltipProvider>,
  );
  await userEvent.click(screen.getByRole("button", { name: /retry/i }));
  expect(retry).toHaveBeenCalledOnce();
  current.unmount();
  env.state.mockReturnValue({ isPending: false, error: null, data: undefined, refetch: retry });
  const missing = view();
  expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
  missing.unmount();
  env.state.mockReturnValue({
    isPending: false,
    error: null,
    data: [],
    stop: { mutate: stop, isPending: false },
  });
  const empty = view();
  expect(screen.getByText("Delegate work while you keep talking")).toBeInTheDocument();
  empty.unmount();
  env.state.mockReturnValue({
    isPending: false,
    error: null,
    data: [
      {
        id: "t",
        title: "Export bug",
        conversation_id: "child",
        status: "running",
        delivery: "pending",
      },
    ],
    stop: { mutate: stop, isPending: false },
  });
  view();
  await userEvent.click(screen.getByRole("button", { name: "Stop Export bug" }));
  expect(stop).toHaveBeenCalledWith("t");
});
