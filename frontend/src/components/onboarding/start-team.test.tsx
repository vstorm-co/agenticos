import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { StartTeam } from "./start-team";
const env = vi.hoisted(() => ({ local: false, refetch: vi.fn() }));
vi.mock("@/lib/local-server", () => ({ isLoopbackAddress: () => env.local }));
vi.mock("@/hooks/use-members", () => ({
  useMembers: () => ({ members: [], error: null, isLoading: false, refetch: env.refetch }),
}));
vi.mock("@/hooks/use-start", () => ({ useMemberStartPreview: () => ({}) }));
vi.mock("@/components/teams/invite-member-dialog", () => ({
  InviteMemberDialog: ({ open }: { open: boolean }) =>
    open ? <div role="dialog">Invitation</div> : null,
}));
beforeEach(() => {
  env.local = false;
});
it("requires an explicit action to open a real team invitation", async () => {
  render(<StartTeam orgId="org" />);
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Invite a teammate" }));
  expect(screen.getByRole("dialog")).toBeVisible();
});
it("explains that loopback cannot admit teammates and prevents an unusable invitation", () => {
  env.local = true;
  render(<StartTeam orgId="org" />);
  expect(screen.getByRole("note")).toHaveTextContent(/local address/i);
  expect(screen.getByRole("button", { name: "Invite a teammate" })).toBeDisabled();
});
