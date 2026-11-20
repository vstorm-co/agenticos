import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ConfigureStep } from "./sync-source-configure-step";
import { apiClient } from "@/lib/api-client";
import type { ConnectorInfo, SyncSourceCreate } from "@/lib/rag-api";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

const SCHEMA = {
  type: "object" as const,
  properties: { folder_id: { type: "string" as const, title: "Google Drive Folder ID" } },
  required: ["folder_id"],
};

const GDRIVE: ConnectorInfo = {
  type: "gdrive",
  name: "Google Drive",
  enabled: true,
  config_schema: SCHEMA,
  secret_kind: "gcp_service_account",
};

const FORM: SyncSourceCreate = {
  name: "Engineering docs",
  connector_type: "gdrive",
  collection_name: "handbook",
  config: {},
  secret_id: null,
  connected_account_id: null,
  organizational_unit: null,
  sync_mode: "full",
  schedule_minutes: null,
};

const HINT = /Paste the folder ID/;

beforeEach(() => {
  vi.mocked(apiClient.get).mockResolvedValue({ drives: [], folders: [] });
});

function renderStep(connector: ConnectorInfo, form: SyncSourceCreate) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ConfigureStep connector={connector} form={form} setForm={vi.fn()} />
    </QueryClientProvider>,
  );
}

describe("the folder of a Drive source", () => {
  it("tells a service-account setup where the folder ID comes from, beside the typed field", () => {
    renderStep(GDRIVE, FORM);

    expect(screen.getByText(HINT)).toBeVisible();
    expect(screen.getByLabelText(/Google Drive Folder ID/)).toBeVisible();
  });

  it("does not show that hint once the folder is browsed through a connected account", () => {
    renderStep(GDRIVE, { ...FORM, connected_account_id: "account-1" });

    expect(screen.getByText("Folder to sync", { exact: false })).toBeVisible();
    expect(screen.queryByText(HINT)).toBeNull();
  });

  it("does not show it for a connector that has no Drive folder", () => {
    renderStep({ ...GDRIVE, type: "s3", name: "S3" }, FORM);

    expect(screen.queryByText(HINT)).toBeNull();
  });
});
