import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import type { RoutineSourceReview } from "@/lib/routine-sources-api";
import type { Trigger } from "@/types/triggers";
import { SourceConsentsPanel } from "./source-consents-panel";

const state = vi.hoisted(() => ({
  data: undefined as RoutineSourceReview | undefined,
  error: null as Error | null,
  loading: false,
  pending: false,
  save: vi.fn(),
  refetch: vi.fn(),
}));
vi.mock("@/hooks/use-routine-sources", () => ({
  useRoutineSources: () => ({
    data: state.data,
    error: state.error,
    isLoading: state.loading,
    replace: { mutate: state.save, isPending: state.pending },
    refetch: state.refetch,
  }),
}));
const trigger = { id: "routine", agent_id: "agent" } as Trigger;
vi.mock("@/components/branding/branding-provider", () => ({
  useBranding: () => ({ appName: "AgenticOS", logoUrl: null }),
}));
beforeEach(() => {
  state.data = {
    current: false,
    review_token: "exact-review",
    version_id: "version",
    resources: ["Knowledge · id"],
    accounts: ["Work mailbox · id"],
    unavailable_sources: [],
  };
  state.error = null;
  state.loading = false;
  state.pending = false;
  state.save.mockReset();
  state.refetch.mockReset();
});
it("shows physical accounts and resources and submits only the displayed review", async () => {
  render(<SourceConsentsPanel trigger={trigger} />);
  expect(screen.getByText("Work mailbox · id")).toBeVisible();
  expect(screen.getByText("Knowledge · id")).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Approve these sources" }));
  expect(state.save).toHaveBeenCalledWith("exact-review");
});
it("groups named sources by kind, folded to counts, and says when one is gone", async () => {
  if (state.data) {
    state.data.items = [
      { kind: "platform" },
      { kind: "skill", id: "s1", name: "deck-review" },
      { kind: "skill", id: "s2", name: null },
      { kind: "table", id: "t1", name: "Leads", detail: "read/create" },
    ];
  }
  render(<SourceConsentsPanel trigger={trigger} />);
  expect(screen.queryByText("Knowledge · id")).not.toBeInTheDocument();
  await userEvent.click(screen.getByText("Skills (2)"));
  expect(screen.getByText("deck-review")).toBeVisible();
  expect(screen.getByText("No longer available")).toHaveAttribute("title", "s2");
  await userEvent.click(screen.getByText("Tables (1)"));
  expect(screen.getByText("Leads")).toHaveTextContent("Leads · read/create");
  await userEvent.click(screen.getByText("Platform (1)"));
  expect(screen.getByText("AgenticOS")).toBeVisible();
});
it.each(["current", "pending", "unavailable"])("cannot approve while %s", (reason) => {
  if (reason === "pending") state.pending = true;
  else if (state.data) {
    if (reason === "current") state.data.current = true;
    else state.data.unavailable_sources = ["Work mailbox"];
  }
  render(<SourceConsentsPanel trigger={trigger} />);
  expect(screen.getByRole("button", { name: "Approve these sources" })).toBeDisabled();
});
it("shows a load error and retries without offering a consent", async () => {
  state.error = new Error("Offline");
  render(<SourceConsentsPanel trigger={trigger} />);
  expect(screen.queryByRole("button", { name: "Approve these sources" })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Try again" }));
  expect(state.refetch).toHaveBeenCalledOnce();
});
it("does not offer an approval until loading finishes", () => {
  state.loading = true;
  render(<SourceConsentsPanel trigger={trigger} />);
  expect(screen.queryByRole("button", { name: "Approve these sources" })).not.toBeInTheDocument();
});
it("does not offer consent when there is no review data", () => {
  state.data = undefined;
  render(<SourceConsentsPanel trigger={trigger} />);
  expect(screen.queryByRole("button", { name: "Approve these sources" })).not.toBeInTheDocument();
});
