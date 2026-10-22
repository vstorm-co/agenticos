import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MirageSection } from "./mirage-section";
import type { CapabilityBindingSpec, CapabilityCatalogEntry } from "@/types/agents";
import type { MirageBackend } from "@/types/mirage";

/**
 * The virtual terminal's folders (#2191): each picks a service, and the service
 * decides the rest of its row - the options, and how it signs in.
 */

const backends = vi.fn();
vi.mock("@/hooks/use-mirage-backends", () => ({ useMirageBackends: () => backends() }));
const accounts = vi.fn();
vi.mock("@/hooks/use-connected-accounts", () => ({
  useConnectedAccounts: (...args: unknown[]) => accounts(...args),
}));
const can = vi.fn();
vi.mock("@/hooks/use-permissions", () => ({ usePermissions: () => ({ can }) }));
const secrets = vi.fn();
vi.mock("@/hooks", async (original) => ({
  ...(await original<typeof import("@/hooks")>()),
  useSecrets: () => secrets(),
}));

function backend(overrides: Partial<MirageBackend> & Pick<MirageBackend, "name">): MirageBackend {
  return {
    title: overrides.name,
    group: "files",
    credential: "none",
    available: true,
    reason: null,
    options_schema: { type: "object", properties: {} },
    secret_fields: [],
    required_secrets: [],
    address_fields: [],
    ...overrides,
  };
}

const RAM = backend({ name: "ram", title: "Scratch space", group: "scratch" });
const GITHUB = backend({
  name: "github",
  title: "GitHub",
  credential: "fields",
  secret_fields: ["token", "app_key"],
  required_secrets: ["token"],
  options_schema: {
    type: "object",
    properties: { repo: { type: "string", title: "Repository" } },
  },
});
const GDRIVE = backend({ name: "gdrive", title: "Google Drive", credential: "google" });
const ONEDRIVE = backend({ name: "onedrive", title: "OneDrive", credential: "microsoft" });
const S3 = backend({ name: "s3", title: "Amazon S3", available: false, reason: "Not installed" });

const DEFINITION: CapabilityCatalogEntry = {
  recommended: null,
  id: "mirage",
  name: "Virtual terminal",
  category: "files",
  description: "Mounts services as folders.",
  side_effecting: true,
  voice: "hand_off",
  scopes: [],
  tools: [],
  contracts: [],
  config_schema: {
    type: "object",
    required: ["mounts"],
    properties: {
      mounts: { type: "array", title: "Folders" },
      hidden_paths: { type: "array", items: { type: "string" }, title: "Hidden paths" },
    },
  },
  requires_secret: null,
};

function mount(
  config: Record<string, unknown>,
  { problems = [] }: { problems?: { field: string; message: string }[] } = {},
) {
  const onChange = vi.fn();
  render(
    <MirageSection
      definition={DEFINITION}
      binding={
        {
          id: "mirage",
          config,
          approval: "default",
          tool_approval: {},
          tool_overrides: {},
          secret_id: null,
          enabled: true,
        } satisfies CapabilityBindingSpec
      }
      configProblems={problems}
      onChange={onChange}
    />,
  );
  return onChange;
}

/** The mounts the last change wrote. */
function written(onChange: ReturnType<typeof vi.fn>) {
  return onChange.mock.lastCall?.[0].config.mounts;
}

beforeEach(() => {
  vi.clearAllMocks();
  backends.mockReturnValue({
    data: { installed: true, items: [RAM, GITHUB, GDRIVE, ONEDRIVE, S3] },
    isError: false,
  });
  accounts.mockReturnValue({ accounts: [{ id: "acc-1", email: "ops@acme.com" }] });
  can.mockReturnValue(true);
  secrets.mockReturnValue({
    secrets: [
      { id: "s-gh", name: "GitHub token", kind: "api_key", hint: "abcd" },
      { id: "s-entra", name: "Acme Entra", kind: "entra_app", hint: "wxyz" },
    ],
    isLoading: false,
  });
});

describe("the folders", () => {
  it("draws nothing for a capability the catalog no longer has", () => {
    const { container } = render(
      <MirageSection
        definition={undefined}
        binding={{
          id: "mirage",
          config: {},
          approval: "default",
          tool_approval: {},
          tool_overrides: {},
          secret_id: null,
          enabled: true,
        }}
        onChange={vi.fn()}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("adds a folder on the first service that can be mounted, under a free name", async () => {
    const onChange = mount({ mounts: [{ path: "/ram/", backend: "ram" }] });

    await userEvent.click(screen.getByRole("button", { name: "Add folder" }));

    expect(written(onChange)).toEqual([
      { path: "/ram/", backend: "ram" },
      { path: "/ram-2/", backend: "ram", mode: "read", options: {}, secrets: {}, account: null },
    ]);
  });

  it("offers no folder to add when nothing can be mounted", () => {
    backends.mockReturnValue({ data: { installed: false, items: [] }, isError: false });
    mount({});

    expect(screen.getByRole("button", { name: "Add folder" })).toBeDisabled();
    expect(screen.getByText(/does not have the virtual terminal installed/)).toBeInTheDocument();
  });

  it("says so when the services could not be read", () => {
    backends.mockReturnValue({ data: undefined, isError: true });
    mount({ mounts: "not a list" });

    expect(screen.getByText("The list of services could not be loaded.")).toBeInTheDocument();
  });

  it("renames and removes a folder", async () => {
    const onChange = mount({ mounts: [{ path: "/a/", backend: "ram" }] });

    await userEvent.type(screen.getByLabelText("Folder"), "b");
    expect(written(onChange)).toEqual([{ path: "/a/b", backend: "ram" }]);

    await userEvent.click(screen.getByRole("button", { name: "Remove /a/" }));
    expect(written(onChange)).toEqual([]);
  });

  it("names a service it cannot mount, and why", async () => {
    mount({ mounts: [{ path: "/a/", backend: "ram" }] });

    await userEvent.click(screen.getByLabelText("Service"));

    expect(await screen.findByRole("option", { name: /Amazon S3/ })).toHaveAttribute(
      "aria-disabled",
      "true",
    );
    expect(screen.getByText("Not installed")).toBeInTheDocument();
  });

  it("drops what belonged to the last service when another is chosen", async () => {
    const onChange = mount({
      mounts: [
        { path: "/a/", backend: "github", secrets: { token: "s-gh" }, options: { repo: "r" } },
      ],
    });

    await userEvent.click(screen.getByLabelText("Service"));
    await userEvent.click(await screen.findByRole("option", { name: "Google Drive" }));

    expect(written(onChange)).toEqual([
      {
        path: "/a/",
        backend: "gdrive",
        mode: undefined,
        options: {},
        secrets: {},
        account: { kind: "personal" },
      },
    ]);
  });

  it("shows a stored service this deployment no longer offers by name", () => {
    mount({ mounts: [{ path: "/a/", backend: "dropbox" }] });

    expect(screen.getByLabelText("Service")).toHaveTextContent("dropbox is not available here");
  });

  it("asks about approval only once a folder is writable", async () => {
    const onChange = mount({ mounts: [{ path: "/a/", backend: "ram" }] });
    expect(screen.queryByLabelText("Approve each write")).toBeNull();

    await userEvent.click(screen.getByLabelText("The agent may write here"));
    expect(written(onChange)).toEqual([{ path: "/a/", backend: "ram", mode: "write" }]);
  });

  it("turns approval off for a writable folder, and back to read only", async () => {
    const onChange = mount({ mounts: [{ path: "/a/", backend: "ram", mode: "write" }] });

    await userEvent.click(screen.getByLabelText("Approve each write"));
    expect(written(onChange)).toEqual([
      { path: "/a/", backend: "ram", mode: "write", approve_writes: false },
    ]);

    await userEvent.click(screen.getByLabelText("The agent may write here"));
    expect(written(onChange)).toEqual([{ path: "/a/", backend: "ram", mode: "read" }]);
  });

  it("edits one folder of several and leaves the rest as they were", async () => {
    const onChange = mount({
      mounts: [
        { path: "/a/", backend: "ram" },
        { path: "/b/", backend: "ram" },
      ],
    });

    await userEvent.type(screen.getByDisplayValue("/b/"), "c");

    expect(written(onChange)).toEqual([
      { path: "/a/", backend: "ram" },
      { path: "/b/c", backend: "ram" },
    ]);
  });

  it("draws only the folders for a schema with no other fields", () => {
    render(
      <MirageSection
        definition={{ ...DEFINITION, config_schema: { type: "object" } }}
        binding={{
          id: "mirage",
          config: {},
          approval: "default",
          tool_approval: {},
          tool_overrides: {},
          secret_id: null,
          enabled: true,
        }}
        onChange={vi.fn()}
      />,
    );

    expect(screen.queryByText("Hidden paths")).toBeNull();
  });

  it("puts the server's refusals under the folder they are about", () => {
    mount(
      { mounts: [{ path: "/a/", backend: "ram" }] },
      {
        problems: [
          { field: "capabilities.mirage.config.mounts.0", message: "Folder is taken" },
          { field: "capabilities.mirage.config.mounts.0.path", message: "Not a folder name" },
          { field: "capabilities.mirage.config.mounts", message: "Too many folders" },
        ],
      },
    );

    expect(screen.getByText("Folder is taken")).toBeInTheDocument();
    expect(screen.getByText("Not a folder name")).toBeInTheDocument();
    expect(screen.getByText("Too many folders")).toBeInTheDocument();
  });

  it("draws the shell's own limits from the schema, and the folders only once", () => {
    mount({ mounts: [{ path: "/a/", backend: "ram" }], hidden_paths: [] });

    expect(screen.getByText("Hidden paths")).toBeInTheDocument();
    expect(screen.getAllByText("Folders")).toHaveLength(1);
  });

  it("keeps the folders when one of the shell's limits changes", async () => {
    const onChange = mount({ mounts: [{ path: "/a/", backend: "ram" }] });

    await userEvent.type(screen.getByLabelText("Hidden paths"), "/a/x/");

    expect(onChange.mock.lastCall?.[0].config).toEqual({
      mounts: [{ path: "/a/", backend: "ram" }],
      hidden_paths: ["/a/x/"],
    });
  });
});

describe("how a folder signs in", () => {
  it("picks a vault key for each of the service's fields, and clears an optional one", async () => {
    const onChange = mount({
      mounts: [{ path: "/code/", backend: "github", secrets: { app_key: "s-gh" } }],
    });

    await userEvent.click(screen.getByLabelText("Secret for token"));
    await userEvent.click(await screen.findByRole("option", { name: /GitHub token/ }));
    expect(written(onChange)[0].secrets).toEqual({ app_key: "s-gh", token: "s-gh" });

    await userEvent.click(screen.getByLabelText("Secret for app_key"));
    await userEvent.click(await screen.findByRole("option", { name: "None" }));
    expect(written(onChange)[0].secrets).toEqual({});
  });

  it("offers only keys, never an Entra app, for a service's own fields", async () => {
    mount({ mounts: [{ path: "/code/", backend: "github" }] });

    await userEvent.click(screen.getByLabelText("Secret for token"));

    expect(screen.queryByRole("option", { name: /Acme Entra/ })).toBeNull();
  });

  it("sends somebody with no suitable key to the vault", () => {
    secrets.mockReturnValue({ secrets: [], isLoading: false });
    mount({ mounts: [{ path: "/files/", backend: "onedrive" }] });

    expect(screen.getByRole("link", { name: "vault" })).toHaveAttribute("href", "/vault");
  });

  it("signs a Microsoft service in as an Entra app", async () => {
    const onChange = mount({ mounts: [{ path: "/files/", backend: "onedrive" }] });

    await userEvent.click(screen.getByLabelText("Entra app"));
    await userEvent.click(await screen.findByRole("option", { name: /Acme Entra/ }));

    expect(written(onChange)[0].secrets).toEqual({ app: "s-entra" });
  });

  it("reads a Google service as each person, or as an account the organization connected", async () => {
    const onChange = mount({
      mounts: [{ path: "/drive/", backend: "gdrive", account: { kind: "personal" } }],
    });
    expect(screen.getByText(/sees their own accounts/)).toBeInTheDocument();

    await userEvent.click(screen.getByLabelText("Account"));
    await userEvent.click(await screen.findByRole("option", { name: "ops@acme.com" }));
    expect(written(onChange)[0].account).toEqual({
      kind: "organization",
      connection_id: "acc-1",
    });
  });

  it("goes back to each person's own accounts", async () => {
    const onChange = mount({
      mounts: [
        {
          path: "/drive/",
          backend: "gdrive",
          account: { kind: "organization", connection_id: "acc-1" },
        },
      ],
    });
    expect(screen.getByLabelText("Account")).toHaveTextContent("ops@acme.com");

    await userEvent.click(screen.getByLabelText("Account"));
    await userEvent.click(
      await screen.findByRole("option", { name: "Each person's own accounts" }),
    );
    expect(written(onChange)[0].account).toEqual({ kind: "personal" });
  });

  it("does not ask for the organization's accounts without the right to list them", () => {
    can.mockReturnValue(false);
    mount({ mounts: [{ path: "/drive/", backend: "gdrive" }] });

    expect(accounts).toHaveBeenCalledWith("organization", { enabled: false });
  });

  it("writes the service's own options beside the folder", async () => {
    const onChange = mount({ mounts: [{ path: "/code/", backend: "github" }] });

    await userEvent.type(screen.getByLabelText("Repository"), "r");

    expect(written(onChange)[0].options).toEqual({ repo: "r" });
  });
});
