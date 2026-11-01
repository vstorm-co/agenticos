import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { toast } from "sonner";

import type { NodeInstance } from "@/lib/workflows/types";

import { CurlImport } from "./curl-import";

const mutateAsync = vi.fn();
const can = vi.fn();
vi.mock("@/hooks", () => ({
  useSecrets: () => ({ kinds: [], create: { mutateAsync, isPending: false } }),
  usePermissions: () => ({ can }),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), warning: vi.fn(), error: vi.fn() } }));
vi.mock("@/components/vault/secret-dialog", () => ({
  AddSecretDialog: ({
    initial,
    onSubmit,
    onOpenChange,
  }: {
    initial: { name: string; value: Record<string, unknown> };
    onSubmit: (data: object) => Promise<unknown>;
    onOpenChange: (open: boolean) => void;
  }) => (
    <div>
      <button type="button" onClick={() => onOpenChange(false)}>
        back
      </button>
      <p>vault form for {initial.name}</p>
      <p>starts with {JSON.stringify(initial.value)}</p>
      <button type="button" onClick={() => void onSubmit({ name: initial.name })}>
        store it
      </button>
    </div>
  ),
}));

const NODE: NodeInstance = {
  id: "h",
  definition_id: "http.request",
  definition_version: 1,
  config: { timeout_seconds: 5, headers: { Old: "1" }, auth: { kind: "none" } },
  layout: { x: 0, y: 0 },
} as NodeInstance;

function mount(node: NodeInstance = NODE) {
  const updateNodeConfig = vi.fn();
  const upsertBinding = vi.fn();
  render(
    <CurlImport
      node={node}
      disabled={false}
      updateNodeConfig={updateNodeConfig}
      upsertBinding={upsertBinding}
    />,
  );
  return { updateNodeConfig, upsertBinding };
}

async function paste(command: string) {
  await userEvent.click(screen.getByRole("button", { name: "Import cURL" }));
  fireEvent.change(screen.getByLabelText("cURL command"), { target: { value: command } });
  await userEvent.click(screen.getByRole("button", { name: "Import" }));
}

beforeEach(() => {
  vi.clearAllMocks();
  can.mockReturnValue(true);
  mutateAsync.mockResolvedValue({ id: "sec-1" });
});

describe("CurlImport", () => {
  it("fills the method, URL, headers and body, and keeps the step's auth", async () => {
    const { updateNodeConfig, upsertBinding } = mount();
    await paste(
      `curl -X POST https://api.example.com/leads -H 'Accept: application/json' -d '{"a":1}'`,
    );

    expect(updateNodeConfig).toHaveBeenCalledWith("h", {
      timeout_seconds: 5,
      method: "POST",
      headers: { Accept: "application/json" },
      auth: { kind: "none" },
    });
    expect(upsertBinding).toHaveBeenCalledWith({
      target_node_id: "h",
      target_field: "url",
      source: { kind: "literal", value: "https://api.example.com/leads" },
    });
    expect(upsertBinding).toHaveBeenCalledWith(
      expect.objectContaining({
        target_field: "body",
        source: { kind: "literal", value: { a: 1 } },
      }),
    );
    expect(toast.success).toHaveBeenCalled();
    expect(screen.queryByLabelText("cURL command")).toBeNull();
  });

  it("drops the headers a command does not carry, and warns about a body it cannot send", async () => {
    const { updateNodeConfig } = mount({ ...NODE, config: { headers: { Old: "1" } } });
    await paste(`curl https://api.example.com -d 'a=1'`);
    expect(updateNodeConfig).toHaveBeenCalledWith("h", { method: "POST" });
    expect(toast.warning).toHaveBeenCalled();
  });

  it("says why a command cannot be read, and clears it as it is edited", async () => {
    mount();
    await paste("wget https://x");
    expect(screen.getByText("This does not start with curl.")).toBeVisible();
    fireEvent.change(screen.getByLabelText("cURL command"), { target: { value: "curl" } });
    expect(screen.queryByText("This does not start with curl.")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByLabelText("cURL command")).toBeNull();
  });

  it("lifts a credential out, then stores it in the vault and points the step at it", async () => {
    const { updateNodeConfig } = mount();
    await paste(`curl https://api.example.com/x -H 'X-Api-Key: k-123'`);

    expect(updateNodeConfig).toHaveBeenLastCalledWith(
      "h",
      expect.objectContaining({ auth: { kind: "header", header_name: "X-Api-Key" } }),
    );
    expect(JSON.stringify(updateNodeConfig.mock.calls)).not.toContain("k-123");
    await userEvent.click(screen.getByRole("button", { name: "Store in the vault" }));
    expect(screen.getByText("vault form for api.example.com token")).toBeVisible();
    expect(
      screen.getByText('starts with {"token":"k-123","origins":["https://api.example.com"]}'),
    ).toBeVisible();

    await userEvent.click(screen.getByRole("button", { name: "store it" }));
    await waitFor(() =>
      expect(updateNodeConfig).toHaveBeenLastCalledWith(
        "h",
        expect.objectContaining({ auth: { kind: "none", secret_id: "sec-1" } }),
      ),
    );
  });

  it.each([
    [`curl -u ada:pw https://api.example.com`, { kind: "basic" }, '"username":"ada"'],
    [`curl 'https://api.example.com?api_key=q1'`, { kind: "query", query_name: "api_key" }, "q1"],
    [`curl https://api.example.com -H 'Authorization: Bearer b1'`, { kind: "bearer" }, "b1"],
  ])("sets the step to send %s's credential the same way", async (command, auth, carried) => {
    const { updateNodeConfig } = mount();
    await paste(command);
    expect(updateNodeConfig).toHaveBeenLastCalledWith("h", expect.objectContaining({ auth }));
    await userEvent.click(screen.getByRole("button", { name: "Store in the vault" }));
    expect(screen.getByText(new RegExp(carried))).toBeVisible();
  });

  it("closes, forgetting the command, on Escape", async () => {
    mount();
    await userEvent.click(screen.getByRole("button", { name: "Import cURL" }));
    fireEvent.change(screen.getByLabelText("cURL command"), { target: { value: "curl x" } });
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByLabelText("cURL command")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Import cURL" }));
    expect(screen.getByLabelText("cURL command")).toHaveValue("");
  });

  it("goes back to the credential when the vault form is closed unsaved", async () => {
    mount();
    await paste(`curl https://api.example.com -H 'Authorization: Bearer b1'`);
    await userEvent.click(screen.getByRole("button", { name: "Store in the vault" }));
    await userEvent.click(screen.getByRole("button", { name: "back" }));
    expect(screen.getByRole("button", { name: "Store in the vault" })).toBeVisible();
  });

  it("asks someone else to store it for a member who may not, and forgets it on Not now", async () => {
    can.mockReturnValue(false);
    mount();
    await paste(`curl https://api.example.com -H 'Authorization: Bearer b1'`);
    expect(screen.getByText(/Ask someone who may store secrets/)).toBeVisible();
    expect(screen.queryByRole("button", { name: "Store in the vault" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Not now" }));
    expect(screen.queryByText(/Ask someone/)).toBeNull();
  });
});
