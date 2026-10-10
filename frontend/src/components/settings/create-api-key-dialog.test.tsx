import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CreateApiKeyDialog } from "./create-api-key-dialog";
import type { ApiKeyCreated, ApiKeyScopeCatalog } from "@/types/api-keys";

const toastError = vi.fn();
vi.mock("@/components/public-config/public-config-provider", () => ({
  usePublicConfig: () => ({ apiUrl: "https://api.example" }),
}));
vi.mock("sonner", () => ({ toast: { error: (...args: unknown[]) => toastError(...args) } }));

const CATALOG: ApiKeyScopeCatalog = {
  scopes: ["agents:view", "collections:view", "collections:edit"],
  presets: [
    { id: "read_only", scopes: ["agents:view", "collections:view"] },
    { id: "knowledge_ingest", scopes: ["collections:view", "collections:edit"] },
  ],
};

const CREATED: ApiKeyCreated = {
  id: "k1",
  name: "Nightly import",
  prefix: "aos_0123abcd",
  scopes: ["agents:view", "collections:view"],
  user_id: "u1",
  issuer_email: "ada@example.com",
  status: "active",
  expires_at: null,
  last_used_at: null,
  revoked_at: null,
  created_at: "2026-10-09T10:00:00Z",
  key: "aos_0123abcdsecret",
};

function open(onCreate = vi.fn().mockResolvedValue(CREATED), onOpenChange = vi.fn()) {
  render(
    <CreateApiKeyDialog
      open
      onOpenChange={onOpenChange}
      catalog={CATALOG}
      onCreate={onCreate}
      busy={false}
    />,
  );
  return { onCreate, onOpenChange };
}

async function pick(label: string, option: string) {
  await userEvent.click(screen.getByLabelText(label));
  await userEvent.click(await screen.findByRole("option", { name: option }));
}

describe("CreateApiKeyDialog", () => {
  beforeEach(() => vi.clearAllMocks());

  it("issues the first preset by default and then shows the key, once", async () => {
    const { onCreate, onOpenChange } = open();

    expect(screen.getByRole("button", { name: "Create" })).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Name"), "Nightly import");
    await userEvent.click(screen.getByRole("button", { name: "Create" }));

    const [sent] = onCreate.mock.lastCall ?? [];
    expect(sent?.scopes).toEqual(["agents:view", "collections:view"]);
    expect(new Date(sent?.expires_at ?? 0).getTime()).toBeGreaterThan(Date.now());
    expect(await screen.findByDisplayValue("aos_0123abcdsecret")).toBeInTheDocument();
    // The key goes to the API's origin, never to the console's proxy.
    expect(
      screen.getByText(/https:\/\/api\.example\/api\/v1\/me\/permissions/),
    ).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("issues exactly the permissions ticked under Custom, with no expiry when asked", async () => {
    const { onCreate } = open();

    await userEvent.type(screen.getByLabelText("Name"), "ci");
    await pick("Access", "Custom");
    expect(screen.getByRole("button", { name: "Create" })).toBeDisabled();
    await userEvent.click(screen.getByRole("checkbox", { name: "collections:edit" }));
    await userEvent.click(screen.getByRole("checkbox", { name: "agents:view" }));
    await userEvent.click(screen.getByRole("checkbox", { name: "agents:view" }));
    await pick("Expires", "Never");
    await userEvent.click(screen.getByRole("button", { name: "Create" }));

    expect(onCreate).toHaveBeenCalledWith({
      name: "ci",
      scopes: ["collections:edit"],
      expires_at: null,
    });
  });

  it("keeps the form and toasts the refusal when the server says no", async () => {
    open(vi.fn().mockRejectedValue(new Error("refused")));

    await userEvent.type(screen.getByLabelText("Name"), "ci");
    await pick("Access", "Knowledge ingest");
    await userEvent.click(screen.getByRole("button", { name: "Create" }));

    expect(toastError).toHaveBeenCalled();
    expect(screen.getByLabelText("Name")).toHaveValue("ci");
  });

  it("offers Custom alone to a caller with no preset", () => {
    render(
      <CreateApiKeyDialog
        open
        onOpenChange={vi.fn()}
        catalog={{ scopes: ["agents:view"], presets: [] }}
        onCreate={vi.fn()}
        busy={false}
      />,
    );

    expect(screen.getAllByRole("checkbox")).toHaveLength(1);
  });
});
