import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ConnectionDialog } from "./connection-dialog";
import { ApiError } from "@/lib/api-error";
import type { SandboxConnectionRecord } from "@/lib/sandbox-connections-api";
import { providerMarkIn } from "@/test-utils/brand-marks";

interface VaultKey {
  id: string;
  name: string;
  kind: string;
  hint: string;
  /** What the key is for. Absent for one stored against no service at all. */
  purpose?: string;
}

const state = vi.hoisted(() => ({
  secrets: [{ id: "s-1", name: "Sandbox token", kind: "api_key", hint: "4242" }] as VaultKey[],
  local: null as {
    url: string | null;
    token_available: boolean;
    registered_connection_id: string | null;
  } | null,
  storeCredential: vi.fn(async () => "s-local"),
  probe: vi.fn(async () => ({ runtimes: [{ alias: "python", description: "Python 3.12" }] })),
  runtimes: [
    { alias: "coding", description: "Python with git", image: "python:3.12-slim", builds: true },
    {
      alias: "python-minimal",
      description: "stdlib only",
      image: "python:3.12-slim",
      builds: true,
    },
  ],
}));

vi.mock("@/hooks", () => ({
  useSecrets: () => ({ secrets: state.secrets }),
  useLocalSandboxService: () => ({
    local: state.local,
    runtimes: state.runtimes,
    isLoading: false,
    storeCredential: state.storeCredential,
    probe: state.probe,
  }),
}));

// The real inline form writes to the vault and is covered by its own tests. What
// this dialog owes it is the callback: a key added there is the key chosen here.
vi.mock("@/components/vault/inline-secret", () => ({
  InlineSecret: ({ onCreated }: { onCreated: (id: string) => void }) => (
    <button type="button" onClick={() => onCreated("s-new")}>
      Add key
    </button>
  ),
}));

function connection(overrides: Partial<SandboxConnectionRecord> = {}): SandboxConnectionRecord {
  return {
    id: "c-1",
    name: "Local Docker",
    kind: "docker",
    base_url: "http://sandboxd:8080",
    secret_id: "s-1",
    default_runtime: "python",
    is_default: true,
    is_active: true,
    created_at: "2026-08-03T00:00:00Z",
    updated_at: null,
    ...overrides,
  };
}

function mount(editing: SandboxConnectionRecord | null = null) {
  const onSubmit = vi.fn().mockResolvedValue(undefined);
  const onOpenChange = vi.fn();
  render(<ConnectionDialog editing={editing} onOpenChange={onOpenChange} onSubmit={onSubmit} />);
  return { onSubmit, onOpenChange };
}

beforeEach(() => {
  vi.clearAllMocks();
  state.secrets = [{ id: "s-1", name: "Sandbox token", kind: "api_key", hint: "4242" }];
  state.local = null;
  state.storeCredential = vi.fn(async () => "s-local");
  state.probe = vi.fn(async () => ({
    runtimes: [{ alias: "python", description: "Python 3.12" }],
  }));
});

describe("ConnectionDialog", () => {
  it("opens empty for a new connection and refuses to save nothing", () => {
    mount();

    expect(screen.getByLabelText("Name")).toHaveValue("");
    expect(screen.getByRole("button", { name: "Add connection" })).toBeDisabled();
  });

  it("refuses a container connection with no address", async () => {
    // It would resolve and then fail to connect on every session, inside
    // somebody's conversation rather than in this form.
    mount();

    await userEvent.type(screen.getByLabelText("Name"), "Big box");

    expect(screen.getByRole("button", { name: "Add connection" })).toBeDisabled();
  });

  it("saves once it has a name and somewhere to reach", async () => {
    const { onSubmit } = mount();

    await userEvent.type(screen.getByLabelText("Name"), "Big box");
    await userEvent.type(screen.getByLabelText("Address"), "http://big:8080");
    await userEvent.click(screen.getByRole("button", { name: "Add connection" }));

    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({ name: "Big box", kind: "docker", base_url: "http://big:8080" }),
    );
  });

  it("opens on the row it was given, for an edit", () => {
    mount(connection());

    expect(screen.getByLabelText("Name")).toHaveValue("Local Docker");
    expect(screen.getByLabelText("Address")).toHaveValue("http://sandboxd:8080");
    expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();
  });

  it("asks for no address at all once the kind is Daytona", async () => {
    // Their API has one; asking an operator to type it invites a typo in the
    // field nothing validates.
    mount();

    await userEvent.click(screen.getByLabelText("Kind"));
    await userEvent.click(screen.getByRole("option", { name: /Daytona/ }));

    expect(screen.queryByLabelText("Address")).toBeNull();
  });

  it("clears an address typed before the kind changed", async () => {
    const { onSubmit } = mount();

    await userEvent.type(screen.getByLabelText("Name"), "Daytona");
    await userEvent.type(screen.getByLabelText("Address"), "http://typo:8080");
    await userEvent.click(screen.getByLabelText("Kind"));
    await userEvent.click(screen.getByRole("option", { name: /Daytona/ }));
    await userEvent.click(screen.getByRole("button", { name: "Add connection" }));

    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ base_url: null }));
  });

  it("drops a credential chosen for the other kind of service", async () => {
    // A Daytona key handed to a sandboxd is a credential sent to the wrong host.
    const { onSubmit } = mount(connection());

    await userEvent.click(screen.getByLabelText("Kind"));
    await userEvent.click(screen.getByRole("option", { name: /Daytona/ }));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ secret_id: null }));
  });

  it("takes a key from the vault by reference, never by value", async () => {
    const { onSubmit } = mount(connection({ secret_id: null }));

    await userEvent.click(screen.getByLabelText("Credential"));
    await userEvent.click(screen.getByRole("option", { name: /Sandbox token/ }));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ secret_id: "s-1" }));
  });

  it("draws each key's own mark and masked tail, and a monogram for a custom one", async () => {
    // Any API key in the vault can be offered here, so the mark is the one
    // thing that says which service a row's token actually belongs to. A key
    // stored for no particular service has no logo anywhere - that is the
    // normal case, and a monogram is what keeps it from being a blank gap.
    state.secrets = [
      { id: "s-1", name: "Sandbox token", kind: "api_key", hint: "4242" },
      { id: "s-2", name: "Daytona prod", kind: "api_key", hint: "7777", purpose: "daytona" },
      { id: "s-3", name: "Acme webhook", kind: "api_key", hint: "1111", purpose: "openai" },
    ];
    mount(connection({ secret_id: null }));

    await userEvent.click(screen.getByLabelText("Credential"));

    const marked = screen.getByRole("option", { name: /Acme webhook/ });
    expect(providerMarkIn(marked)).toBe("openai");
    expect(marked).toHaveTextContent("····1111");
    // `daytona` is a service with no compiled-in mark, and so is a key with no
    // purpose at all. Both draw the monogram of what they are for - the initial
    // in front of the name - rather than leaving the square empty.
    expect(screen.getByRole("option", { name: /Daytona prod/ }).textContent).toMatch(/^dDaytona/);
    expect(screen.getByRole("option", { name: /Sandbox token/ }).textContent).toMatch(/^cSandbox/);
  });

  it("carries the chosen key's mark on the closed trigger", async () => {
    state.secrets = [
      { id: "s-1", name: "OpenAI prod", kind: "api_key", hint: "4242", purpose: "openai" },
    ];
    mount(connection());

    expect(providerMarkIn(screen.getByLabelText("Credential"))).toBe("openai");
  });

  it("takes one added inline as well", async () => {
    const { onSubmit } = mount(connection({ secret_id: null }));

    await userEvent.click(screen.getByRole("button", { name: "Add key" }));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ secret_id: "s-new" }));
  });

  it("sends an empty runtime as unset rather than as an alias nothing knows", async () => {
    const { onSubmit } = mount(connection({ default_runtime: null }));

    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ default_runtime: null }));
  });

  it("records the runtime an agent gets when its own spec names none", async () => {
    // Picked from the catalog, which is populated the moment the form opens.
    const { onSubmit } = mount(connection({ default_runtime: null }));

    await userEvent.click(screen.getByRole("combobox", { name: "Default runtime" }));
    await userEvent.click(await screen.findByRole("option", { name: /python-minimal/ }));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({ default_runtime: "python-minimal" }),
    );
  });

  it("offers switching a connection off only once it exists", async () => {
    // There is nothing to switch off about a host nobody has registered.
    const { onSubmit } = mount();
    expect(screen.queryByLabelText("Switched on")).toBeNull();

    await userEvent.type(screen.getByLabelText("Name"), "Big box");
    await userEvent.type(screen.getByLabelText("Address"), "http://big:8080");
    await userEvent.click(screen.getByRole("button", { name: "Add connection" }));

    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ is_active: true }));
  });

  it("switches an existing one off", async () => {
    const { onSubmit } = mount(connection());

    await userEvent.click(screen.getByLabelText("Switched on"));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ is_active: false }));
  });

  it("promotes a connection to the organization's default", async () => {
    const { onSubmit } = mount(connection({ is_default: false }));

    await userEvent.click(screen.getByLabelText("Use this by default"));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ is_default: true }));
  });

  it("closes itself once the save went through", async () => {
    const { onOpenChange } = mount(connection());

    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("says why a save was refused, and stays open so the form is not lost", async () => {
    // A rejection that escaped the click handler reached nobody at all.
    const onSubmit = vi.fn().mockRejectedValue(new Error("that name is taken"));
    const onOpenChange = vi.fn();
    render(
      <ConnectionDialog editing={connection()} onOpenChange={onOpenChange} onSubmit={onSubmit} />,
    );

    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(screen.getByText("that name is taken")).toBeVisible();
    expect(onOpenChange).not.toHaveBeenCalledWith(false);
  });

  /**
   * Which box to fix, not just what went wrong.
   *
   * `_check_shape` and the probe both answer `details.fields` against
   * `base_url`, and a duplicate name is a 409 this form places itself through
   * `identifiedBy` (#891). Before that, all three were one red line at the
   * bottom of a dialog with four inputs in it.
   */
  it("marks the address the service refused", async () => {
    const message = "A container connection needs the address its sandbox service answers on";
    const onSubmit = vi.fn().mockRejectedValue(
      new ApiError(400, message, {
        error: {
          code: "BAD_REQUEST",
          message,
          details: { fields: [{ field: "base_url", message }] },
        },
      }),
    );
    render(<ConnectionDialog editing={connection()} onOpenChange={vi.fn()} onSubmit={onSubmit} />);

    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    const address = screen.getByLabelText("Address");
    expect(address).toHaveAttribute("aria-invalid", "true");
    expect(address).toHaveAccessibleDescription(message);
    expect(screen.getByLabelText("Name")).not.toHaveAttribute("aria-invalid", "true");
  });

  it("marks the name a duplicate is about, and does not repeat it below", async () => {
    const message = "A sandbox connection by that name already exists";
    const onSubmit = vi.fn().mockRejectedValue(
      new ApiError(409, message, {
        error: { code: "ALREADY_EXISTS", message, details: { name: "Local Docker" } },
      }),
    );
    render(<ConnectionDialog editing={connection()} onOpenChange={vi.fn()} onSubmit={onSubmit} />);

    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(screen.getByLabelText("Name")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getAllByText(message)).toHaveLength(1);
  });

  it("clears the mark as soon as the address changes", async () => {
    const message = "The sandbox service at http://typo:8080 did not answer";
    const onSubmit = vi.fn().mockRejectedValue(
      new ApiError(400, message, {
        error: {
          code: "BAD_REQUEST",
          message,
          details: { fields: [{ field: "base_url", message }] },
        },
      }),
    );
    render(<ConnectionDialog editing={connection()} onOpenChange={vi.fn()} onSubmit={onSubmit} />);

    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await userEvent.type(screen.getByLabelText("Address"), "0");

    expect(screen.getByLabelText("Address")).not.toHaveAttribute("aria-invalid", "true");
  });

  it("clears the mark as soon as the name changes", async () => {
    const message = "A sandbox connection by that name already exists";
    const onSubmit = vi.fn().mockRejectedValue(
      new ApiError(409, message, {
        error: { code: "ALREADY_EXISTS", message, details: { name: "Local Docker" } },
      }),
    );
    render(<ConnectionDialog editing={connection()} onOpenChange={vi.fn()} onSubmit={onSubmit} />);

    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await userEvent.type(screen.getByLabelText("Name"), "2");

    expect(screen.getByLabelText("Name")).not.toHaveAttribute("aria-invalid", "true");
  });

  it("cancelling closes without saving", async () => {
    const { onSubmit, onOpenChange } = mount(connection());

    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(onSubmit).not.toHaveBeenCalled();
  });

  describe("a service this deployment is already running", () => {
    it("fills in the address that answered", async () => {
      // Nobody should have to know that a `make dev` sandbox service answers at
      // `http://sandboxd:8080`.
      state.local = {
        url: "http://sandboxd:8080",
        token_available: true,
        registered_connection_id: null,
      };
      mount();

      expect(await screen.findByLabelText("Address")).toHaveValue("http://sandboxd:8080");
      expect(screen.getByText(/answered at http:\/\/sandboxd:8080/)).toBeVisible();
    });

    it("stops prefilling once somebody clears the field to type another host", async () => {
      state.local = {
        url: "http://sandboxd:8080",
        token_available: false,
        registered_connection_id: null,
      };
      mount();
      const address = await screen.findByLabelText("Address");

      await userEvent.clear(address);

      expect(address).toHaveValue("");
    });

    it("says when this organization already registered that address", async () => {
      // Otherwise somebody adds a second row for one host and then wonders which
      // of the two an agent gets.
      state.local = {
        url: "http://sandboxd:8080",
        token_available: false,
        registered_connection_id: "c-9",
      };
      mount();

      expect(await screen.findByText(/already has a connection pointing there/)).toBeVisible();
    });

    it("offers nothing when no service answered", () => {
      mount();

      expect(screen.getByLabelText("Address")).toHaveValue("");
      expect(screen.queryByText(/answered at/)).toBeNull();
    });

    it("does not offer to change where an existing connection points", () => {
      // An operator editing a row has already decided its host; probing on their
      // behalf would be offering to move it.
      state.local = {
        url: "http://elsewhere:8080",
        token_available: true,
        registered_connection_id: null,
      };
      mount(connection());

      expect(screen.getByLabelText("Address")).toHaveValue("http://sandboxd:8080");
    });
  });

  describe("the token this deployment already holds", () => {
    it("stores it in the vault and selects it, rather than asking for the value", async () => {
      // `make sandbox-token` wrote it to `backend/.env` and compose handed it to
      // the service. Asking somebody to go and copy it back out is friction with
      // nothing behind it.
      state.local = {
        url: "http://sandboxd:8080",
        token_available: true,
        registered_connection_id: null,
      };
      const { onSubmit } = mount();
      await userEvent.type(screen.getByLabelText("Name"), "Local Docker");

      await userEvent.click(
        await screen.findByRole("button", { name: /Store it in the vault and use it/ }),
      );
      await userEvent.click(screen.getByRole("button", { name: "Add connection" }));

      expect(state.storeCredential).toHaveBeenCalled();
      expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ secret_id: "s-local" }));
    });

    it("says why storing it failed instead of leaving the button dead", async () => {
      state.local = { url: "http://s:8080", token_available: true, registered_connection_id: null };
      state.storeCredential = vi.fn(async () => {
        throw new Error("This deployment carries no sandbox service token");
      });
      mount();

      await userEvent.click(
        await screen.findByRole("button", { name: /Store it in the vault and use it/ }),
      );

      expect(screen.getByText("This deployment carries no sandbox service token")).toBeVisible();
    });

    it("offers nothing when the deployment holds no token", () => {
      state.local = {
        url: "http://s:8080",
        token_available: false,
        registered_connection_id: null,
      };
      mount();

      expect(screen.queryByRole("button", { name: /Store it in the vault/ })).toBeNull();
    });
  });

  describe("the runtime the service will actually accept", () => {
    it("is a populated list before anything has been asked of a host", async () => {
      // A select that only filled in after pressing a button was a select nobody
      // would find, and a typo in free text is stored happily and refused at the
      // first tool call inside somebody's conversation.
      mount();

      await userEvent.click(screen.getByRole("combobox", { name: "Default runtime" }));

      expect(await screen.findByRole("option", { name: /coding/ })).toBeVisible();
      expect(state.probe).not.toHaveBeenCalled();
    });

    it("asks the service which of them this host allows", async () => {
      mount(connection());

      await userEvent.click(screen.getByRole("button", { name: /Test and check this host/ }));

      expect(state.probe).toHaveBeenCalledWith("http://sandboxd:8080", "s-1");
      expect(await screen.findByText(/This host allows 1 of them/)).toBeVisible();
    });

    it("cannot be asked before there is an address and a key to ask with", () => {
      mount();

      expect(screen.queryByRole("button", { name: /Test and check this host/ })).toBeNull();
    });

    it("reports a service that refused the key where the form can see it", async () => {
      state.probe = vi.fn(async () => {
        throw new Error("The sandbox service refused this connection's credential");
      });
      mount(connection());

      await userEvent.click(screen.getByRole("button", { name: /Test and check this host/ }));

      expect(
        await screen.findByText("The sandbox service refused this connection's credential"),
      ).toBeVisible();
    });

    it("keeps a free-text field for Daytona, which publishes no list", async () => {
      const { onSubmit } = mount(connection({ kind: "daytona", base_url: null }));
      const field = screen.getByLabelText("Default runtime");

      expect(field).toHaveValue("python");
      expect(screen.queryByRole("button", { name: /Test and list runtimes/ })).toBeNull();

      await userEvent.clear(field);
      await userEvent.type(field, "ubuntu-24");
      await userEvent.click(screen.getByRole("button", { name: "Save" }));

      expect(onSubmit).toHaveBeenCalledWith(
        expect.objectContaining({ default_runtime: "ubuntu-24" }),
      );
    });
  });
});
