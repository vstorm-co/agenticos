import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ReusableIntegrations } from "./reusable-integrations";
import { apiClient } from "@/lib/api-client";
import { useOrgStore } from "@/stores";
import { DEFAULT_INGESTION_CONFIG } from "@/lib/ingestion-config";
import type { SyncSourceRead } from "@/lib/rag-api";
import type { KnowledgeBase } from "@/types";
import type { OrgRole } from "@/types/organization";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const ORG_ID = "org-1";

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const UNASSIGNED: SyncSourceRead = {
  id: "s1",
  organization_id: ORG_ID,
  name: "Handbook drive",
  connector_type: "gdrive",
  collection_name: null,
  config: { folder_id: "abc" },
  secret_id: null,
  sync_mode: "full",
  schedule_minutes: null,
  is_active: true,
  last_sync_at: null,
  last_sync_status: null,
  last_error: null,
  created_at: "2026-07-01T00:00:00Z",
};

function kb(id: string, name: string, collection: string): KnowledgeBase {
  return {
    id,
    name,
    description: null,
    collection_name: collection,
    scope: "org",
    organization_id: ORG_ID,
    owner_user_id: null,
    is_default: false,
    ingestion_config: DEFAULT_INGESTION_CONFIG,
    embedding_model: "text-embedding-3-large",
    embedding_dim: 3072,
    created_at: "2026-07-01T00:00:00Z",
    updated_at: null,
    document_count: 0,
    indexed_count: 0,
    chunk_count: 0,
  };
}

const TARGETS = [kb("kb-1", "Handbook", "handbook_a1"), kb("kb-2", "Runbooks", "runbooks_b2")];

function serve(role: OrgRole, sources: SyncSourceRead[]) {
  vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
    if (path === "/me/permissions")
      return {
        organization_id: ORG_ID,
        role,
        is_app_admin: false,
        // The section keys on the permission the endpoints gate on, so the
        // fake answers the way the server would for each role.
        permissions:
          role === "owner" || role === "admin" || role === "builder"
            ? [{ permission: "connections:manage", scope: "all" }]
            : [],
      };
    if (path === `/orgs/${ORG_ID}/integrations`) return { items: sources, total: sources.length };
    if (path === `/orgs/${ORG_ID}/integrations/connectors`)
      return {
        items: [{ type: "gdrive", name: "Google Drive", config_schema: {}, enabled: true }],
      };
    throw new Error(`unexpected GET ${path}`);
  });
}

describe("ReusableIntegrations", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useOrgStore.setState({ activeOrgId: ORG_ID });
  });

  it("lets one integration be used in a second knowledge base", async () => {
    // The journey the deleted organization page owned, and the reason this
    // section exists: configure a connector once, then feed two collections
    // from it without retyping the credentials - which are masked and could not
    // be retyped anyway.
    serve("owner", [UNASSIGNED]);
    vi.mocked(apiClient.post).mockResolvedValue({ ...UNASSIGNED, id: "s2" });
    render(<ReusableIntegrations targets={TARGETS} />, { wrapper });

    await userEvent.click(await screen.findByRole("button", { name: "Use in…" }));
    await userEvent.click(screen.getByRole("combobox", { name: "Knowledge base" }));
    await userEvent.click(screen.getByRole("option", { name: "Runbooks" }));
    await userEvent.click(screen.getByRole("button", { name: "Add to knowledge base" }));

    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith("/kb/kb-2/sync-sources/s1/clone", {
        collection_name: "runbooks_b2",
        name: "Handbook drive (Runbooks)",
      }),
    );
    // Still listed: the next collection needs it too.
    expect(screen.getByText("Handbook drive")).toBeInTheDocument();
  });

  it("shows a member nothing, and asks the endpoint nothing", async () => {
    // The routes behind this section are owner/admin-only. A section that could
    // only report a refusal is worse than no section, and a request that can
    // only 403 is worse than no request.
    serve("member", [UNASSIGNED]);
    render(<ReusableIntegrations targets={TARGETS} />, { wrapper });

    await waitFor(() => expect(apiClient.get).toHaveBeenCalledWith("/me/permissions"));
    expect(screen.queryByText("Reusable integrations")).not.toBeInTheDocument();
    expect(apiClient.get).not.toHaveBeenCalledWith(`/orgs/${ORG_ID}/integrations`);
  });
});
