import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { EnvironmentConnections } from "./environment-connections";
import type { AgentEnvironment, EnvironmentConnection } from "@/types/agents";

const servers = [
  { id: "crm", name: "crm", is_enabled: true, authorized: true },
  { id: "crm-sandbox", name: "crm-sandbox", is_enabled: true, authorized: true },
  { id: "crm-retired", name: "crm-retired", is_enabled: false, authorized: true },
  { id: "crm-unsigned", name: "crm-unsigned", is_enabled: true, authorized: false },
];
const secrets = [
  { id: "mail-live", name: "Mail live", kind: "api_key", purpose: "custom" },
  { id: "mail-test", name: "Mail test", kind: "api_key", purpose: "custom" },
  { id: "search", name: "Search", kind: "api_key", purpose: "tavily" },
  { id: "unlabelled", name: "Unlabelled", kind: "api_key" },
];

vi.mock("@/hooks", () => ({
  useOrgMcpConnections: () => ({ connections: servers }),
  useSecrets: () => ({ secrets }),
}));

function staging(connections: EnvironmentConnection[] = []): AgentEnvironment {
  return {
    id: "staging-id",
    agent_id: "a1",
    name: "staging",
    version_id: "v2-id",
    version: 2,
    is_default: false,
    tracks_latest: false,
    behind_by: 0,
    logfire_token_secret_id: null,
    service_name: null,
    connections,
    guard_suite_ids: [],
    created_at: "2026-10-13T10:00:00Z",
  };
}

const onSave = vi.fn();

beforeEach(() => {
  onSave.mockReset();
});

async function pick(combobox: string, option: string) {
  await userEvent.click(screen.getByRole("combobox", { name: combobox }));
  await userEvent.click(screen.getByRole("option", { name: option }));
}

describe("an environment's test connections", () => {
  it("replaces one test side and keeps the rest of the list", async () => {
    render(
      <EnvironmentConnections
        environment={staging([
          { kind: "mcp", production_id: "crm", test_id: null },
          { kind: "secret", production_id: "mail-live", test_id: "mail-test" },
        ])}
        saving={false}
        onSave={onSave}
      />,
    );

    await pick("Test replacement for crm", "crm-sandbox");

    expect(onSave).toHaveBeenCalledWith([
      { kind: "mcp", production_id: "crm", test_id: "crm-sandbox" },
      { kind: "secret", production_id: "mail-live", test_id: "mail-test" },
    ]);
  });

  it("switches a binding off rather than dropping it", async () => {
    render(
      <EnvironmentConnections
        environment={staging([
          { kind: "secret", production_id: "mail-live", test_id: "mail-test" },
        ])}
        saving={false}
        onSave={onSave}
      />,
    );

    await pick("Test replacement for Mail live", "Off in this environment");

    expect(onSave).toHaveBeenCalledWith([
      { kind: "secret", production_id: "mail-live", test_id: null },
    ]);
  });

  it("offers only a test key of the same kind and purpose", async () => {
    // The server refuses a Tavily key standing in for a mail key.
    render(
      <EnvironmentConnections
        environment={staging([{ kind: "secret", production_id: "mail-live", test_id: null }])}
        saving={false}
        onSave={onSave}
      />,
    );

    await userEvent.click(screen.getByRole("combobox", { name: "Test replacement for Mail live" }));
    const offered = screen.getAllByRole("option").map((option) => option.textContent);

    // A key saved without a purpose is a `custom` one, like the mail keys.
    expect(offered).toEqual(["Off in this environment", "Mail test", "Unlabelled"]);
  });

  it("never offers a test connection a run could not reach", async () => {
    render(
      <EnvironmentConnections
        environment={staging([{ kind: "mcp", production_id: "crm", test_id: null }])}
        saving={false}
        onSave={onSave}
      />,
    );

    await userEvent.click(screen.getByRole("combobox", { name: "Test replacement for crm" }));
    const offered = screen.getAllByRole("option").map((option) => option.textContent);

    expect(offered).toEqual(["Off in this environment", "crm-sandbox"]);
  });

  it("says a binding is off when its test connection is disabled or not signed in", () => {
    render(
      <EnvironmentConnections
        environment={staging([
          { kind: "mcp", production_id: "crm", test_id: "crm-retired" },
          { kind: "mcp", production_id: "crm-sandbox", test_id: "crm-unsigned" },
          { kind: "secret", production_id: "mail-live", test_id: "mail-test" },
        ])}
        saving={false}
        onSave={onSave}
      />,
    );

    expect(screen.getByRole("combobox", { name: "Test replacement for crm" })).toHaveTextContent(
      "crm-retired",
    );
    expect(
      screen.getAllByText("Off here: the test connection is disabled or not signed in"),
    ).toHaveLength(2);
  });

  it("still names what the caller cannot list, shortened, instead of an empty row", () => {
    render(
      <EnvironmentConnections
        environment={staging([
          { kind: "mcp", production_id: "0123456789abcdef", test_id: "fedcba9876543210" },
        ])}
        saving={false}
        onSave={onSave}
      />,
    );

    expect(screen.getByText("01234567")).toBeInTheDocument();
    expect(
      screen.getByRole("combobox", { name: "Test replacement for 01234567" }),
    ).toHaveTextContent("fedcba98");
  });

  it("removes an override", async () => {
    render(
      <EnvironmentConnections
        environment={staging([{ kind: "mcp", production_id: "crm", test_id: "crm-sandbox" }])}
        saving={false}
        onSave={onSave}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: "Remove crm" }));

    expect(onSave).toHaveBeenCalledWith([]);
  });

  it("adds an MCP override, never offering a binding already overridden", async () => {
    render(
      <EnvironmentConnections
        environment={staging([{ kind: "secret", production_id: "mail-live", test_id: null }])}
        saving={false}
        onSave={onSave}
      />,
    );
    const add = screen.getByRole("button", { name: "Add" });
    expect(add).toBeDisabled();

    await pick("Production", "crm");
    await pick("Test replacement", "crm-sandbox");
    await userEvent.click(add);

    expect(onSave).toHaveBeenCalledWith([
      { kind: "secret", production_id: "mail-live", test_id: null },
      { kind: "mcp", production_id: "crm", test_id: "crm-sandbox" },
    ]);
    expect(screen.getByRole("button", { name: "Add" })).toBeDisabled();
  });

  it("adds a vault key switched off, and offers each production key once", async () => {
    render(
      <EnvironmentConnections
        environment={staging([{ kind: "secret", production_id: "mail-live", test_id: null }])}
        saving={false}
        onSave={onSave}
      />,
    );

    await pick("What to replace", "Vault key");
    await userEvent.click(screen.getByRole("combobox", { name: "Production" }));
    const listbox = screen.getByRole("listbox");
    expect(within(listbox).queryByRole("option", { name: "Mail live" })).not.toBeInTheDocument();
    await userEvent.click(within(listbox).getByRole("option", { name: "Unlabelled" }));
    await pick("Test replacement", "Off in this environment");
    await userEvent.click(screen.getByRole("button", { name: "Add" }));

    expect(onSave).toHaveBeenLastCalledWith([
      { kind: "secret", production_id: "mail-live", test_id: null },
      { kind: "secret", production_id: "unlabelled", test_id: null },
    ]);
  });

  it("holds every control while a save is in flight", () => {
    render(
      <EnvironmentConnections
        environment={staging([{ kind: "mcp", production_id: "crm", test_id: null }])}
        saving
        onSave={onSave}
      />,
    );

    expect(screen.getByRole("combobox", { name: "Test replacement for crm" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Remove crm" })).toBeDisabled();
  });
});
