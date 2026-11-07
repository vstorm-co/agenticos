import { beforeEach, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { StartChecklist } from "./start-checklist";
const state = vi.hoisted(() => ({
  data: { organization_id: "org", dismissed: false, has_result: false },
  error: null as unknown,
  save: { mutate: vi.fn(), isPending: false, isError: false },
}));
vi.mock("@/hooks/use-start", () => ({ useStart: () => state }));
beforeEach(() => {
  state.data = { organization_id: "org", dismissed: false, has_result: false };
  state.error = null;
  state.save.mutate.mockClear();
});
it("links to the shared start and saves a dismissal without claiming success", async () => {
  render(<StartChecklist orgId="org" />);
  expect(screen.getByRole("link", { name: "Get started" })).toHaveAttribute("href", "/onboarding");
  await userEvent.click(screen.getByRole("button", { name: "Later" }));
  expect(state.save.mutate).toHaveBeenCalledWith({ dismissed: true });
});
it.each(["other-organization", "dismissed", "result", "error"])(
  "does not offer an irrelevant start: %s",
  (reason) => {
    if (reason === "other-organization") state.data.organization_id = "other";
    if (reason === "dismissed") state.data.dismissed = true;
    if (reason === "result") state.data.has_result = true;
    if (reason === "error") state.error = new Error("offline");
    render(<StartChecklist orgId="org" />);
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  },
);
