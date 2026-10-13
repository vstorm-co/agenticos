import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { kindInfo, useSecretPurposes, useSecrets } from "./use-secrets";
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

  it("cancels the in-flight list read before invalidating, so a stale refetch cannot win (#130)", async () => {
    // invalidateQueries dedupes onto a fetch already running; a list read that
    // began before the rotate committed would otherwise resolve with the
    // pre-write list and the table would show the old value until a reload.
    vi.mocked(apiClient.patch).mockResolvedValue({ name: "Zendesk", hint: "8B1P" });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const cancelSpy = vi.spyOn(client, "cancelQueries");
    const invalidateSpy = vi.spyOn(client, "invalidateQueries");
    const scoped = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );

    const { result } = renderHook(() => useSecrets(), { wrapper: scoped });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await result.current.rotate.mutateAsync({
      id: "s1",
      value: { kind: "api_key", api_key: "sk-thenewone8B1P" },
    });

    expect(cancelSpy).toHaveBeenCalledWith({ queryKey: ["secrets", "list"] });
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["secrets", "list"] });
    const cancelOrder = cancelSpy.mock.invocationCallOrder[0] ?? 0;
    const invalidateOrder = invalidateSpy.mock.invocationCallOrder[0] ?? 0;
    expect(cancelOrder).toBeGreaterThan(0);
    expect(cancelOrder).toBeLessThan(invalidateOrder);
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

describe("deleting a secret", () => {
  beforeEach(() => vi.clearAllMocks());

  it("says why a deletion was refused, unlike the writing mutations", async () => {
    // Create and rotate leave their refusals to the dialog, which has a field to
    // put "that name is taken" beside. A deletion has no form and no field, so a
    // silent failure would read as a row that refused to disappear.
    const { toast } = await import("sonner");
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(apiClient.delete).mockRejectedValue(new Error("A published agent uses it"));
    const { result } = renderHook(() => useSecrets(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await expect(result.current.remove.mutateAsync("sec-1")).rejects.toThrow();

    expect(toast.error).toHaveBeenCalledWith("A published agent uses it");
  });
});

/**
 * What a secret can be for.
 *
 * Fetched rather than listed in code: the model providers are generated from the
 * same table the runtime builds clients out of, so a copy here would drift the
 * moment somebody adds one - and the symptom is a provider nobody can key.
 */
describe("useSecretPurposes", () => {
  beforeEach(() => vi.clearAllMocks());

  it("reads the deployment's own list", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      items: [{ id: "openai", label: "OpenAI", category: "model_provider" }],
      total: 1,
    });

    const { result } = renderHook(() => useSecretPurposes(), { wrapper });

    await waitFor(() => expect(result.current.purposes).toHaveLength(1));
    expect(apiClient.get).toHaveBeenCalledWith("/secrets/purposes");
  });

  it("offers nothing rather than undefined while the catalog is unread", async () => {
    // The field renders before the answer arrives, and `.map` on undefined is a
    // blank page.
    vi.mocked(apiClient.get).mockRejectedValue(new Error("403"));

    const { result } = renderHook(() => useSecretPurposes(), { wrapper });

    expect(result.current.purposes).toEqual([]);
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.purposes).toEqual([]);
  });
});
