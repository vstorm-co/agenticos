import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ConnectionDialog } from "./connection-dialog";
import { Perm } from "@/types/permissions";
import type { Permission } from "@/types/permissions";

/**
 * The vault write this dialog offers, with the real form rather than a stand-in.
 *
 * `connection-dialog.test.tsx` mocks `InlineSecret` away, which is right for
 * everything it asserts - what the dialog owes the form is a callback - and is
 * exactly why the missing permission check survived there. This renders the real
 * one, so the two halves of #361 are asserted on the surface that has them:
 * storing a sandbox provider's key is `secrets:edit`, and this dialog exists for
 * `connections:manage`.
 */

const state = vi.hoisted(() => ({
  permissions: [] as Permission[],
  create: { mutate: vi.fn(), isPending: false },
}));

vi.mock("@/hooks", () => ({
  useSecrets: () => ({ secrets: [], create: state.create }),
  useLocalSandboxService: () => ({
    local: null,
    runtimes: [],
    isLoading: false,
    storeCredential: vi.fn(),
    probe: vi.fn(),
  }),
  usePermissions: () => ({
    can: (permission: Permission) => state.permissions.includes(permission),
  }),
}));

function mount() {
  render(
    <ConnectionDialog
      editing={null}
      onOpenChange={vi.fn()}
      onSubmit={vi.fn().mockResolvedValue(undefined)}
    />,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  state.permissions = [Perm.connectionsManage, Perm.secretsEdit];
  state.create = { mutate: vi.fn(), isPending: false };
});

describe("storing a sandbox service's token from the connection dialog", () => {
  it("offers the form to a caller who may write to the vault", () => {
    mount();

    expect(
      screen.getByRole("button", { name: "Add a key: Sandbox service token" }),
    ).toBeInTheDocument();
  });

  it("offers none without secrets:edit, and says who can", () => {
    // `connections:manage` is what opens this dialog; the token it authenticates
    // with is a separate write, and an operator registering a service somebody
    // else's key already covers holds the first and not the second.
    state.permissions = [Perm.connectionsManage];
    mount();

    expect(screen.queryByRole("button", { name: "Add a key: Sandbox service token" })).toBeNull();
    // The credential picker stays: choosing a key that is already stored is not
    // a write, and the dialog is still usable for one.
    expect(screen.getByLabelText("Credential")).toBeInTheDocument();
    expect(screen.getByText(/permission you do not hold/)).toBeInTheDocument();
  });
});
