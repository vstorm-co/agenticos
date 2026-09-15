import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { LocalServices } from "./local-services";
import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";
import type { LocalServiceRecord } from "@/lib/local-services-api";

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

function service(overrides: Partial<LocalServiceRecord> = {}): LocalServiceRecord {
  return {
    id: "ls-1",
    organization_id: "org-1",
    kind: "embedding",
    provider: "ollama",
    name: "GPU box",
    base_url: "http://ollama:11434/v1",
    is_active: true,
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
}: {
  manage: boolean;
  appAdmin?: boolean;
  services?: LocalServiceRecord[];
}) {
  vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
    if (path === "/me/permissions")
      return {
        organization_id: "org-1",
        role: manage ? "admin" : "member",
        is_app_admin: appAdmin,
        permissions: manage ? [{ permission: "connections:manage", scope: "all" }] : [],
      };
    if (path === "/local-services") return { items: services, total: services.length };
    throw new Error(`unexpected GET ${path}`);
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(apiClient.post).mockResolvedValue(service({ id: "ls-3", name: "New box" }));
  vi.mocked(apiClient.delete).mockResolvedValue(undefined);
});

describe("LocalServices", () => {
  it("shows a member nothing, and asks the endpoint nothing", async () => {
    serve({ manage: false });
    render(<LocalServices />, { wrapper });

    await waitFor(() => expect(apiClient.get).toHaveBeenCalledWith("/me/permissions"));
    expect(screen.queryByText("Local services")).toBeNull();
    expect(apiClient.get).not.toHaveBeenCalledWith("/local-services");
  });

  it("lists the organization's servers and the deployment's, marked apart", async () => {
    serve({ manage: true });
    render(<LocalServices />, { wrapper });

    expect(await screen.findByText("GPU box")).toBeVisible();
    expect(screen.getByText("Shared OCR (deployment)")).toBeVisible();
    expect(screen.getByText(/http:\/\/ollama:11434\/v1/)).toBeVisible();
  });

  it("says when nothing is registered yet", async () => {
    serve({ manage: true, services: [] });
    render(<LocalServices />, { wrapper });

    expect(await screen.findByText(/Nothing here yet/)).toBeVisible();
  });

  it("registers a server with the provider its kind implies, and no deployment switch", async () => {
    // The provider is not a field: one embedding catalog entry and one parser
    // can stand behind a local server, so the kind decides it.
    serve({ manage: true });
    render(<LocalServices />, { wrapper });
    await screen.findByText("GPU box");

    await userEvent.click(screen.getByRole("button", { name: "Add server" }));
    const dialog = screen.getByRole("dialog");
    expect(screen.queryByLabelText("Deployment-wide")).toBeNull();
    await userEvent.type(screen.getByLabelText("Name"), "New box");
    await userEvent.type(screen.getByLabelText("Address"), "http://ollama-2:11434/v1");
    await userEvent.click(screen.getByRole("button", { name: "Register" }));

    await waitFor(() => expect(apiClient.post).toHaveBeenCalled());
    expect(apiClient.post).toHaveBeenCalledWith("/local-services", {
      name: "New box",
      kind: "embedding",
      provider: "ollama",
      base_url: "http://ollama-2:11434/v1",
    });
    await waitFor(() => expect(dialog).not.toBeInTheDocument());
  });

  it("lets the app admin register for the whole deployment, as an OCR server", async () => {
    serve({ manage: true, appAdmin: true });
    render(<LocalServices />, { wrapper });
    await screen.findByText("GPU box");

    await userEvent.click(screen.getByRole("button", { name: "Add server" }));
    await userEvent.type(screen.getByLabelText("Name"), "Shared OCR 2");
    await userEvent.click(screen.getByLabelText("Kind"));
    await userEvent.click(await screen.findByRole("option", { name: "OCR server (LiteParse)" }));
    await userEvent.type(screen.getByLabelText("Address"), "http://ocr-2:8000");
    await userEvent.click(screen.getByLabelText("Deployment-wide"));
    await userEvent.click(screen.getByRole("button", { name: "Register" }));

    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith("/local-services", {
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
    render(<LocalServices />, { wrapper });
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
    render(<LocalServices />, { wrapper });
    await screen.findByText("GPU box");

    await userEvent.click(screen.getByRole("button", { name: "Remove GPU box" }));
    await userEvent.click(screen.getByRole("button", { name: "Remove" }));

    await waitFor(() => expect(apiClient.delete).toHaveBeenCalledWith("/local-services/ls-1"));
  });

  it("offers a member of the organization no way to remove the deployment's row", async () => {
    // A deployment-wide row is the app admin's; the server would refuse the
    // delete, so the button is not drawn rather than drawn and refused.
    serve({ manage: true });
    render(<LocalServices />, { wrapper });
    await screen.findByText("GPU box");

    expect(screen.queryByRole("button", { name: "Remove Shared OCR" })).toBeNull();
  });

  it("offers the app admin the deployment's row to remove", async () => {
    serve({ manage: true, appAdmin: true });
    render(<LocalServices />, { wrapper });
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
    render(<LocalServices />, { wrapper });

    expect(await screen.findByText(/Failed to load local services|502/)).toBeVisible();
    expect(screen.queryByText(/Nothing here yet/)).toBeNull();
  });
});
