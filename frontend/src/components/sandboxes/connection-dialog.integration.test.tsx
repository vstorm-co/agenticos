import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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
  secrets: [] as { id: string; name: string; kind: string }[],
  probe: vi.fn(),
}));

vi.mock("@/hooks", () => ({
  useSecrets: () => ({ secrets: state.secrets, create: state.create }),
  useLocalSandboxService: () => ({
    local: null,
    runtimes: [],
    isLoading: false,
    storeCredential: vi.fn(),
    probe: state.probe,
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
  state.secrets = [];
  state.probe = vi.fn().mockResolvedValue({ runtimes: [] });
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

/**
 * The runtime list is the sandbox library's catalogue until a host has answered,
 * and a service may have been started with three of its fifteen aliases. The field
 * marks the difference - but only once somebody has asked, so a form filled in and
 * saved without pressing `Test` registered a default the first tool call refuses
 * (#1039).
 */
describe("asking the host what it allows", () => {
  beforeEach(() => {
    state.secrets = [{ id: "s-1", name: "Sandbox token", kind: "api_key" }];
  });

  it("asks as soon as there is an address and a credential", async () => {
    mount();

    await userEvent.type(screen.getByLabelText("Address"), "http://sandboxd:8080");
    await userEvent.click(screen.getByLabelText("Credential"));
    await userEvent.click(await screen.findByRole("option", { name: /Sandbox token/ }));

    await waitFor(() => expect(state.probe).toHaveBeenCalledWith("http://sandboxd:8080", "s-1"));
  });

  it("asks nothing with only half of what it needs", async () => {
    // A request per keystroke would ask about `htt` and be wrong about it; a
    // request with no credential cannot be authorised at all.
    mount();

    await userEvent.type(screen.getByLabelText("Address"), "http://sandboxd:8080");

    await new Promise((resolve) => setTimeout(resolve, 800));
    expect(state.probe).not.toHaveBeenCalled();
  });
});
