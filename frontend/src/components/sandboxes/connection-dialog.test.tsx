import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ConnectionDialog } from "./connection-dialog";
import type { SandboxConnectionRecord } from "@/lib/sandbox-connections-api";

const state = vi.hoisted(() => ({
  secrets: [{ id: "s-1", name: "Sandbox token", kind: "api_key", hint: "4242" }],
}));

vi.mock("@/hooks", () => ({ useSecrets: () => ({ secrets: state.secrets }) }));

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
    const { onSubmit } = mount(connection({ default_runtime: null }));

    await userEvent.type(screen.getByLabelText("Default runtime"), "data-science");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({ default_runtime: "data-science" }),
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

  it("cancelling closes without saving", async () => {
    const { onSubmit, onOpenChange } = mount(connection());

    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(onSubmit).not.toHaveBeenCalled();
  });
});
