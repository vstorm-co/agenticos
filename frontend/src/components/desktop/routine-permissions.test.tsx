import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";

import { RoutinePermissions } from "./routine-permissions";

const native = vi.hoisted(() => ({
  available: true,
  error: false,
  pending: false,
  grants: true,
  revoke: vi.fn(),
}));
vi.mock("@/hooks/use-routine-local-work", () => ({
  useRoutineLocalWork: () => ({
    available: native.available,
    grants: {
      isError: native.error,
      isPending: native.pending,
      data: native.grants
        ? [
            {
              id: "grant",
              name: "Report",
              root: "/work",
              operations: { read: true, write: true, execute: true },
            },
          ]
        : [],
    },
    revoke: { isPending: false, mutate: native.revoke },
  }),
}));
beforeEach(() => {
  native.available = true;
  native.error = false;
  native.pending = false;
  native.grants = true;
  native.revoke.mockReset();
});
it("names the routine, folder and operations and revokes that grant", async () => {
  render(<RoutinePermissions />);
  expect(screen.getByText("Report")).toBeVisible();
  expect(screen.getByText("/work")).toBeVisible();
  expect(screen.getByText("Read · Write · Run commands")).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Revoke" }));
  expect(native.revoke).toHaveBeenCalledWith("grant");
});
it("does not disguise a corrupt store as no permissions", () => {
  native.error = true;
  render(<RoutinePermissions />);
  expect(screen.getByText(/Could not change the routine permission/)).toBeVisible();
  expect(screen.queryByText(/No routine has/)).toBeNull();
});
it("shows an empty inventory explicitly", () => {
  native.grants = false;
  render(<RoutinePermissions />);
  expect(screen.getByText(/No routine has/)).toBeVisible();
});
it("does not display a previous owner's grants on an unpaired device", () => {
  native.available = false;
  render(<RoutinePermissions />);
  expect(screen.queryByText("/work")).toBeNull();
});
