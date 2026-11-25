import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { KnowledgeIntegrations } from "./reusable-integrations";
import { useOrgStore } from "@/stores";
import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";
import type { ServiceConnectionRecord } from "@/lib/service-connections-api";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function service(overrides: Partial<ServiceConnectionRecord> = {}): ServiceConnectionRecord {
  return {
    id: "ls-1",
    organization_id: "org-1",
    kind: "embedding",
    provider: "ollama",
    name: "GPU box",
    base_url: "http://ollama:11434/v1",
    is_active: true,
    secret_id: null,
    requires_key: false,
    created_at: "2026-09-01T00:00:00Z",
    updated_at: null,
    ...overrides,
  };
}

const OWN = service();
const SHARED = service({
  id: "ls-2",
  organization_id: null,
  kind: "ocr",
  provider: "liteparse",
  name: "Shared OCR",
  base_url: "http://ocr:8000",
});

/** Who is asking, and what is registered. The section keys on `connections:manage`. */
function serve({
  manage,
  appAdmin = false,
  services = [OWN, SHARED],
  estimate = { calls: 3, max_calls: 6, knowledge_bases: 1 },
}: {
  manage: boolean;
  appAdmin?: boolean;
  services?: ServiceConnectionRecord[];
  estimate?: { calls: number; max_calls: number; knowledge_bases: number } | "pending" | "error";
}) {
  vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
    if (path === "/me/permissions")
      return {
        organization_id: "org-1",
        role: manage ? "admin" : "member",
        is_app_admin: appAdmin,
        permissions: manage ? [{ permission: "connections:manage", scope: "all" }] : [],
      };
    if (path === "/orgs/org-1/integrations") return { items: [], total: 0 };
    if (path === "/orgs/org-1/integrations/connectors") return { items: [], total: 0 };
    if (path === "/service-connections") return { items: services, total: services.length };
    if (path === "/secrets")
      return {
        items: [{ id: "sec-1", name: "Gateway key", hint: "abcd", purpose: "openai_compatible" }],
        total: 1,
      };
    if (path === "/secrets/kinds") return { items: [] };
    if (path.endsWith("/probe/estimate")) {
      if (estimate === "pending") return new Promise(() => {});
      if (estimate === "error") throw new Error("estimate failed");
      return estimate;
    }
    throw new Error(`unexpected GET ${path}`);
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  useOrgStore.setState({ activeOrgId: "org-1" });
  vi.mocked(apiClient.post).mockResolvedValue(service({ id: "ls-3", name: "New box" }));
  vi.mocked(apiClient.delete).mockResolvedValue(undefined);
});

describe("ServiceConnections", () => {
  it("shows a member nothing, and asks the endpoint nothing", async () => {
    serve({ manage: false });
    render(<KnowledgeIntegrations targets={[]} />, { wrapper });

    await waitFor(() => expect(apiClient.get).toHaveBeenCalledWith("/me/permissions"));
    expect(screen.queryByText("Service connections")).toBeNull();
    expect(apiClient.get).not.toHaveBeenCalledWith("/service-connections");
  });

  it("lists the organization's servers and the deployment's, marked apart", async () => {
    serve({ manage: true });
    render(<KnowledgeIntegrations targets={[]} />, { wrapper });

    expect(await screen.findByText("GPU box")).toBeVisible();
    expect(screen.getByText("Shared OCR (deployment)")).toBeVisible();
    expect(screen.getByText(/http:\/\/ollama:11434\/v1/)).toBeVisible();
  });

  it("says when nothing is registered yet", async () => {
    serve({ manage: true, services: [] });
    render(<KnowledgeIntegrations targets={[]} />, { wrapper });

    expect(await screen.findByText("No integrations yet")).toBeVisible();
  });

  it("registers a server with the first API style of its kind, and no deployment switch", async () => {
    serve({ manage: true });
    render(<KnowledgeIntegrations targets={[]} />, { wrapper });
    await screen.findByText("GPU box");

    await userEvent.click(screen.getByRole("button", { name: "Add server" }));
    const dialog = screen.getByRole("dialog");
    expect(screen.queryByLabelText("Deployment-wide")).toBeNull();
    await userEvent.type(screen.getByLabelText("Name"), "New box");
    await userEvent.type(screen.getByLabelText("Address"), "http://ollama-2:11434/v1");
    await userEvent.click(screen.getByRole("button", { name: "Register" }));

    await waitFor(() => expect(apiClient.post).toHaveBeenCalled());
    expect(apiClient.post).toHaveBeenCalledWith("/service-connections", {
      name: "New box",
      kind: "embedding",
      provider: "ollama",
      base_url: "http://ollama-2:11434/v1",
    });
    await waitFor(() => expect(dialog).not.toBeInTheDocument());
  });

  it("lets the app admin register for the whole deployment, as an OCR server", async () => {
    serve({ manage: true, appAdmin: true });
    render(<KnowledgeIntegrations targets={[]} />, { wrapper });
    await screen.findByText("GPU box");

    await userEvent.click(screen.getByRole("button", { name: "Add server" }));
    await userEvent.type(screen.getByLabelText("Name"), "Shared OCR 2");
    await userEvent.click(screen.getByLabelText("Kind"));
    await userEvent.click(await screen.findByRole("option", { name: "OCR server (LiteParse)" }));
    await userEvent.type(screen.getByLabelText("Address"), "http://ocr-2:8000");
    await userEvent.click(screen.getByLabelText("Deployment-wide"));
    await userEvent.click(screen.getByRole("button", { name: "Register" }));

    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith("/service-connections", {
        name: "Shared OCR 2",
        kind: "ocr",
        provider: "liteparse",
        base_url: "http://ocr-2:8000",
        deployment_wide: true,
      }),
    );
  });

  it("puts the server's refusal under the field it named", async () => {
    vi.mocked(apiClient.post).mockRejectedValueOnce(
      new ApiError(400, "Not an address", {
        error: {
          code: "BAD_REQUEST",
          message: "Not an address",
          details: { fields: [{ field: "base_url", message: "Not an address" }] },
        },
      }),
    );
    serve({ manage: true });
    render(<KnowledgeIntegrations targets={[]} />, { wrapper });
    await screen.findByText("GPU box");

    await userEvent.click(screen.getByRole("button", { name: "Add server" }));
    await userEvent.type(screen.getByLabelText("Name"), "Broken");
    await userEvent.type(screen.getByLabelText("Address"), "nowhere");
    await userEvent.click(screen.getByRole("button", { name: "Register" }));

    expect(await screen.findByText("Not an address")).toBeVisible();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("removes the organization's own server after a confirmation", async () => {
    serve({ manage: true });
    render(<KnowledgeIntegrations targets={[]} />, { wrapper });
    await screen.findByText("GPU box");

    await userEvent.click(screen.getByRole("button", { name: "Remove GPU box" }));
    await userEvent.click(screen.getByRole("button", { name: "Remove" }));

    await waitFor(() => expect(apiClient.delete).toHaveBeenCalledWith("/service-connections/ls-1"));
  });

  it("offers a member of the organization no way to remove the deployment's row", async () => {
    // A deployment-wide row is the app admin's; the server would refuse the
    // delete, so the button is not drawn rather than drawn and refused.
    serve({ manage: true });
    render(<KnowledgeIntegrations targets={[]} />, { wrapper });
    await screen.findByText("GPU box");

    expect(screen.queryByRole("button", { name: "Remove Shared OCR" })).toBeNull();
  });

  it("offers the app admin the deployment's row to remove", async () => {
    serve({ manage: true, appAdmin: true });
    render(<KnowledgeIntegrations targets={[]} />, { wrapper });
    await screen.findByText("GPU box");

    expect(screen.getByRole("button", { name: "Remove Shared OCR" })).toBeInTheDocument();
  });

  it("says when the list could not be read, rather than showing an empty list", async () => {
    vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
      if (path === "/me/permissions")
        return {
          organization_id: "org-1",
          role: "admin",
          is_app_admin: false,
          permissions: [{ permission: "connections:manage", scope: "all" }],
        };
      throw new Error("502 Bad Gateway");
    });
    render(<KnowledgeIntegrations targets={[]} />, { wrapper });

    expect((await screen.findAllByText(/Failed to load service connections|502/))[0]).toBeVisible();
    expect(screen.queryByText(/Nothing here yet/)).toBeNull();
  });

  it("shows the API style and a key badge in the list", async () => {
    serve({
      manage: true,
      services: [
        OWN,
        service({
          id: "ls-9",
          name: "Gateway",
          provider: "openai_compatible",
          base_url: "https://gw.example/v1",
          secret_id: "sec-1",
          requires_key: true,
        }),
      ],
    });
    render(<KnowledgeIntegrations targets={[]} />, { wrapper });

    expect(await screen.findByText("Gateway")).toBeVisible();
    expect(screen.getByText("OpenAI-compatible")).toBeVisible();
    expect(screen.getAllByText("Vault key")).toHaveLength(1);
  });

  it("offers a Vault key only for an organization's OpenAI-compatible connection", async () => {
    serve({ manage: true, appAdmin: true });
    render(<KnowledgeIntegrations targets={[]} />, { wrapper });
    await screen.findByText("GPU box");

    await userEvent.click(screen.getByRole("button", { name: "Add server" }));
    expect(screen.queryByLabelText("Vault key")).toBeNull();

    await userEvent.click(screen.getByLabelText("API style"));
    await userEvent.click(await screen.findByRole("option", { name: "OpenAI-compatible" }));
    expect(screen.getByLabelText("Vault key")).toBeVisible();

    await userEvent.click(screen.getByLabelText("Deployment-wide"));
    expect(screen.queryByLabelText("Vault key")).toBeNull();
    expect(screen.getByText(/deployment-wide connection cannot hold a key/i)).toBeVisible();
  });

  it("posts the chosen key with the connection", async () => {
    serve({ manage: true });
    render(<KnowledgeIntegrations targets={[]} />, { wrapper });
    await screen.findByText("GPU box");

    await userEvent.click(screen.getByRole("button", { name: "Add server" }));
    await userEvent.type(screen.getByLabelText("Name"), "Gateway");
    await userEvent.click(screen.getByLabelText("API style"));
    await userEvent.click(await screen.findByRole("option", { name: "OpenAI-compatible" }));
    await userEvent.type(screen.getByLabelText("Address"), "https://gw.example/v1");
    await userEvent.click(screen.getByLabelText("Vault key"));
    await userEvent.click(await screen.findByRole("option", { name: /Gateway key/ }));
    await userEvent.click(screen.getByRole("button", { name: "Register" }));

    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith("/service-connections", {
        name: "Gateway",
        kind: "embedding",
        provider: "openai_compatible",
        base_url: "https://gw.example/v1",
        secret_id: "sec-1",
      }),
    );
  });

  describe("editing an embedding connection's address", () => {
    const failed = {
      passed: false,
      outcome: "vectors_differ",
      dim: null,
      calls: 6,
      knowledge_bases: [
        {
          knowledge_base_id: "kb-1",
          name: "Handbook",
          outcome: "vectors_differ",
          min_cosine: 0.4,
          calls: 6,
        },
      ],
      probe_token: null,
      expires_at: null,
    };
    const passed = {
      passed: true,
      outcome: "passed",
      dim: 768,
      calls: 3,
      knowledge_bases: [
        {
          knowledge_base_id: "kb-1",
          name: "Handbook",
          outcome: "passed",
          min_cosine: 0.999,
          calls: 3,
        },
      ],
      probe_token: "tok-1",
      expires_at: "2026-11-25T12:10:00Z",
    };

    async function openEdit() {
      serve({ manage: true });
      render(<KnowledgeIntegrations targets={[]} />, { wrapper });
      await screen.findByText("GPU box");
      await userEvent.click(screen.getByRole("button", { name: "Edit GPU box" }));
      return screen.getByRole("dialog");
    }

    const save = () => screen.getByRole("button", { name: "Save" });

    it("says how many probes the test makes before it runs", async () => {
      await openEdit();
      await userEvent.clear(screen.getByLabelText("Address"));
      await userEvent.type(screen.getByLabelText("Address"), "http://ollama-2:11434/v1");

      expect(await screen.findByText("3 probes")).toBeVisible();
      expect(apiClient.post).not.toHaveBeenCalled();
    });

    it("keeps Save disabled after an address edit until the test for that address passes", async () => {
      vi.mocked(apiClient.post).mockResolvedValue(passed);
      await openEdit();
      await userEvent.clear(screen.getByLabelText("Address"));
      await userEvent.type(screen.getByLabelText("Address"), "http://ollama-2:11434/v1");
      expect(save()).toBeDisabled();

      await userEvent.click(screen.getByRole("button", { name: "Test" }));

      expect(await screen.findByText("1 knowledge base keeps its vectors")).toBeVisible();
      expect(apiClient.post).toHaveBeenCalledWith("/service-connections/ls-1/probe", {
        base_url: "http://ollama-2:11434/v1",
      });
      expect(save()).toBeEnabled();
      expect(screen.queryByRole("button", { name: "Save without testing" })).toBeNull();
      await userEvent.click(save());
      await waitFor(() =>
        expect(apiClient.patch).toHaveBeenCalledWith("/service-connections/ls-1", {
          base_url: "http://ollama-2:11434/v1",
          probe_token: "tok-1",
        }),
      );
    });

    it("disables Save again when the address changes after a passing test", async () => {
      vi.mocked(apiClient.post).mockResolvedValue(passed);
      await openEdit();
      await userEvent.clear(screen.getByLabelText("Address"));
      await userEvent.type(screen.getByLabelText("Address"), "http://ollama-2:11434/v1");
      await userEvent.click(screen.getByRole("button", { name: "Test" }));
      await waitFor(() => expect(save()).toBeEnabled());

      await userEvent.type(screen.getByLabelText("Address"), "x");

      expect(save()).toBeDisabled();
    });

    it("names each failed knowledge base and its cause", async () => {
      vi.mocked(apiClient.post).mockResolvedValue(failed);
      await openEdit();
      await userEvent.clear(screen.getByLabelText("Address"));
      await userEvent.type(screen.getByLabelText("Address"), "http://ollama-2:11434/v1");
      await userEvent.click(screen.getByRole("button", { name: "Test" }));

      expect(await screen.findByText(/Handbook:/)).toBeVisible();
      expect(screen.getByText("Create a new knowledge base for these settings.")).toBeVisible();
      expect(save()).toBeDisabled();
    });

    it("saves unverified only after the confirmation", async () => {
      await openEdit();
      await userEvent.clear(screen.getByLabelText("Address"));
      await userEvent.type(screen.getByLabelText("Address"), "http://ollama-2:11434/v1");

      await userEvent.click(screen.getByRole("button", { name: "Save without testing" }));
      expect(apiClient.patch).not.toHaveBeenCalled();
      await userEvent.click(await screen.findByRole("button", { name: "Save anyway" }));

      await waitFor(() =>
        expect(apiClient.patch).toHaveBeenCalledWith("/service-connections/ls-1", {
          base_url: "http://ollama-2:11434/v1",
          unverified: true,
        }),
      );
    });

    it("keeps Test disabled and bills nothing while the estimate is loading", async () => {
      serve({ manage: true, estimate: "pending" });
      render(<KnowledgeIntegrations targets={[]} />, { wrapper });
      await screen.findByText("GPU box");
      await userEvent.click(screen.getByRole("button", { name: "Edit GPU box" }));
      await userEvent.clear(screen.getByLabelText("Address"));
      await userEvent.type(screen.getByLabelText("Address"), "http://ollama-2:11434/v1");

      const test = screen.getByRole("button", { name: "Test" });
      expect(test).toBeDisabled();
      await userEvent.click(test);
      expect(apiClient.post).not.toHaveBeenCalled();
    });

    it("shows why the count is missing and keeps Test disabled when the estimate fails", async () => {
      serve({ manage: true, estimate: "error" });
      render(<KnowledgeIntegrations targets={[]} />, { wrapper });
      await screen.findByText("GPU box");
      await userEvent.click(screen.getByRole("button", { name: "Edit GPU box" }));
      await userEvent.clear(screen.getByLabelText("Address"));
      await userEvent.type(screen.getByLabelText("Address"), "http://ollama-2:11434/v1");

      expect(await screen.findByText("estimate failed")).toBeVisible();
      expect(screen.getByRole("button", { name: "Test" })).toBeDisabled();
    });

    it("enables Test once the estimate is loaded", async () => {
      await openEdit();
      await userEvent.clear(screen.getByLabelText("Address"));
      await userEvent.type(screen.getByLabelText("Address"), "http://ollama-2:11434/v1");

      await screen.findByText("3 probes");
      expect(screen.getByRole("button", { name: "Test" })).toBeEnabled();
    });

    it("locks the kind and the API style in edit mode", async () => {
      await openEdit();

      expect(screen.getByLabelText("Kind")).toBeDisabled();
      expect(screen.getByLabelText("API style")).toBeDisabled();
    });

    it("offers no save without testing on an incomplete form", async () => {
      await openEdit();
      await userEvent.clear(screen.getByLabelText("Address"));
      await userEvent.type(screen.getByLabelText("Address"), "http://x");
      await userEvent.clear(screen.getByLabelText("Name"));

      expect(screen.getByRole("button", { name: "Save without testing" })).toBeDisabled();
    });

    it("tests and saves a key-only change", async () => {
      const gateway = service({
        id: "ls-9",
        name: "Gateway",
        provider: "openai_compatible",
        base_url: "https://gw.example/v1",
        secret_id: "sec-0",
        requires_key: true,
      });
      serve({ manage: true, services: [gateway] });
      vi.mocked(apiClient.post).mockResolvedValue(passed);
      render(<KnowledgeIntegrations targets={[]} />, { wrapper });
      await screen.findByText("Gateway");
      await userEvent.click(screen.getByRole("button", { name: "Edit Gateway" }));
      await userEvent.click(screen.getByLabelText("Vault key"));
      await userEvent.click(await screen.findByRole("option", { name: /Gateway key/ }));
      await userEvent.click(screen.getByRole("button", { name: "Test" }));
      await waitFor(() => expect(save()).toBeEnabled());

      expect(apiClient.post).toHaveBeenCalledWith("/service-connections/ls-9/probe", {
        secret_id: "sec-1",
      });
      await userEvent.click(save());
      await waitFor(() =>
        expect(apiClient.patch).toHaveBeenCalledWith("/service-connections/ls-9", {
          secret_id: "sec-1",
          probe_token: "tok-1",
        }),
      );
    });

    it("does not ask for a test when only the name changes", async () => {
      await openEdit();
      await userEvent.clear(screen.getByLabelText("Name"));
      await userEvent.type(screen.getByLabelText("Name"), "Renamed");

      expect(screen.queryByRole("button", { name: "Test" })).toBeNull();
      await userEvent.click(save());
      await waitFor(() =>
        expect(apiClient.patch).toHaveBeenCalledWith("/service-connections/ls-1", {
          name: "Renamed",
        }),
      );
    });
  });
});

describe("who may edit which row", () => {
  it("hides the edit action on a deployment row from a non-admin and shows it to the app admin", async () => {
    serve({ manage: true });
    const { unmount } = render(<KnowledgeIntegrations targets={[]} />, { wrapper });
    await screen.findByText("GPU box");
    expect(screen.getByRole("button", { name: "Edit GPU box" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Edit Shared OCR" })).toBeNull();
    unmount();

    serve({ manage: true, appAdmin: true });
    render(<KnowledgeIntegrations targets={[]} />, { wrapper });
    await screen.findByText("GPU box");
    expect(screen.getByRole("button", { name: "Edit Shared OCR" })).toBeVisible();
  });
});
