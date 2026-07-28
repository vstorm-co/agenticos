import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { kindInfo, useSecrets } from "./use-secrets";
import { apiClient } from "@/lib/api-client";
import type { SecretKindInfo } from "@/types/secrets";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
const toastSuccess = vi.fn();
vi.mock("sonner", () => ({
  toast: { success: (...args: unknown[]) => toastSuccess(...args), error: vi.fn() },
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const API_KEY: SecretKindInfo = {
  kind: "api_key",
  name: "API key",
  description: "A single token, sent as-is to the service.",
  json_schema: {
    type: "object",
    properties: { api_key: { type: "string", format: "password" } },
    required: ["api_key"],
  },
};

describe("useSecrets", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
  });

  it("loads the stored secrets and the shapes a new one may take", async () => {
    // The kinds are fetched, not listed here: every form on this surface is
    // generated from the schema the server publishes for them.
    const { result } = renderHook(() => useSecrets(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(apiClient.get).toHaveBeenCalledWith("/secrets");
    expect(apiClient.get).toHaveBeenCalledWith("/secrets/kinds");
  });

  it("confirms a stored secret by its hint, never its value", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ name: "Zendesk", hint: "4Q2X" });
    const { result } = renderHook(() => useSecrets(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await result.current.create.mutateAsync({
      name: "Zendesk",
      value: { kind: "api_key", api_key: "sk-notarealtoken4Q2X" },
    });

    const message = toastSuccess.mock.calls.at(-1)?.[0] as string;
    expect(message).toContain("4Q2X");
    expect(message).not.toContain("sk-notarealtoken4Q2X");
  });

  it("rotates in place, keeping the id every agent binding names", async () => {
    // The whole reason rotation is a PATCH and not a delete-and-recreate: a
    // spec references a secret by id, so a new row would leave every agent
    // pointing at something this organization no longer has.
    vi.mocked(apiClient.patch).mockResolvedValue({ name: "Zendesk", hint: "8B1P" });
    const { result } = renderHook(() => useSecrets(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await result.current.rotate.mutateAsync({
      id: "s1",
      value: { kind: "api_key", api_key: "sk-thenewone8B1P" },
    });

    expect(apiClient.patch).toHaveBeenCalledWith("/secrets/s1", {
      value: { kind: "api_key", api_key: "sk-thenewone8B1P" },
    });
    const message = toastSuccess.mock.calls.at(-1)?.[0] as string;
    expect(message).toContain("8B1P");
    expect(message).not.toContain("sk-thenewone8B1P");
  });

  it("says out loud that a rotated value is gone", async () => {
    // Rotation is the one operation here that destroys something. Somebody who
    // has not written the old value down elsewhere needs to know before they
    // discover it.
    vi.mocked(apiClient.patch).mockResolvedValue({ name: "Zendesk", hint: "8B1P" });
    const { result } = renderHook(() => useSecrets(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await result.current.rotate.mutateAsync({ id: "s1", value: { kind: "api_key", api_key: "x" } });

    expect(toastSuccess.mock.calls.at(-1)?.[0]).toMatch(/old value is gone/i);
  });

  it("says deleting a secret breaks the agents bound to it", async () => {
    vi.mocked(apiClient.delete).mockResolvedValue(undefined);
    const { result } = renderHook(() => useSecrets(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await result.current.remove.mutateAsync("s1");

    expect(apiClient.delete).toHaveBeenCalledWith("/secrets/s1");
    expect(toastSuccess.mock.calls.at(-1)?.[0]).toMatch(/fails at its next run/i);
  });
});

describe("kindInfo", () => {
  it("finds the schema a form is generated from", () => {
    expect(kindInfo([API_KEY], "api_key")?.json_schema.required).toEqual(["api_key"]);
  });

  it("returns null for a kind the server did not publish", () => {
    // Rendering an empty form would let somebody store a secret with no value
    // in it. Nothing is the honest answer while the catalog is still loading.
    expect(kindInfo([API_KEY], "azure_openai")).toBeNull();
  });
});
