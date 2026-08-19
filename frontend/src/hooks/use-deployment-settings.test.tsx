import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useDeploymentSettings } from "./use-deployment-settings";
import { apiClient } from "@/lib/api-client";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), patch: vi.fn(), delete: vi.fn(), upload: vi.fn() },
}));
const toastSuccess = vi.fn();
const toastError = vi.fn();
vi.mock("sonner", () => ({
  toast: {
    success: (...args: unknown[]) => toastSuccess(...args),
    error: (...args: unknown[]) => toastError(...args),
  },
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const SETTINGS = {
  app_name: "Acme AI",
  tagline: null,
  description: null,
  logo_version: 7,
  favicon_version: null,
  footer_text: null,
  terms_url: null,
  privacy_url: null,
  signup_mode: "open" as const,
  allowed_email_domains: [],
  maintenance_mode: false,
  maintenance_message: null,
  announcement: null,
  announcement_level: "info" as const,
  updated_at: null,
};

async function loaded() {
  const { result } = renderHook(() => useDeploymentSettings(), { wrapper });
  await waitFor(() => expect(result.current.isLoading).toBe(false));
  return result;
}

describe("reading the deployment settings", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(apiClient.get).mockResolvedValue(SETTINGS);
  });

  it("is one request for the whole form", async () => {
    const result = await loaded();

    expect(apiClient.get).toHaveBeenCalledWith("/admin/settings");
    expect(result.current.settings?.app_name).toBe("Acme AI");
  });

  it("answers null rather than a half-shaped row while it loads", async () => {
    const { result } = renderHook(() => useDeploymentSettings(), { wrapper });

    expect(result.current.settings).toBeNull();
    await waitFor(() => expect(result.current.isLoading).toBe(false));
  });

  it("reports a failed read instead of an empty deployment", async () => {
    // "No settings" and "the request answered 502" are the same pixels otherwise,
    // and a form that renders defaults over an unread row saves them.
    vi.mocked(apiClient.get).mockRejectedValue(new Error("502"));
    const { result } = renderHook(() => useDeploymentSettings(), { wrapper });

    await waitFor(() => expect(result.current.error).toBeTruthy());
    expect(result.current.settings).toBeNull();
  });
});

describe("saving", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(apiClient.get).mockResolvedValue(SETTINGS);
    vi.mocked(apiClient.patch).mockResolvedValue(SETTINGS);
  });

  it("sends only the fields it was given", async () => {
    // A PATCH, so editing the name cannot silently rewrite an announcement
    // somebody else changed meanwhile.
    const result = await loaded();

    await result.current.save.mutateAsync({ app_name: "Acme AI" });

    expect(apiClient.patch).toHaveBeenCalledWith("/admin/settings", { app_name: "Acme AI" });
  });

  it("sends an explicit null, which is how an override is cleared", async () => {
    const result = await loaded();

    await result.current.save.mutateAsync({ tagline: null });

    expect(apiClient.patch).toHaveBeenCalledWith("/admin/settings", { tagline: null });
  });

  it("says so when it worked", async () => {
    const result = await loaded();

    await result.current.save.mutateAsync({ app_name: "Acme AI" });

    expect(toastSuccess).toHaveBeenCalled();
  });

  it("surfaces a refusal rather than swallowing it", async () => {
    vi.mocked(apiClient.patch).mockRejectedValue(new Error("nope"));
    const result = await loaded();

    await expect(result.current.save.mutateAsync({ app_name: "x" })).rejects.toThrow();
    expect(toastError).toHaveBeenCalled();
  });
});

describe("the two marks", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(apiClient.get).mockResolvedValue(SETTINGS);
    vi.mocked(apiClient.upload).mockResolvedValue(SETTINGS);
    vi.mocked(apiClient.delete).mockResolvedValue(SETTINGS);
  });

  it.each(["logo", "favicon"] as const)("uploads the %s to its own endpoint", async (kind) => {
    const result = await loaded();
    const file = new File(["png"], "mark.png", { type: "image/png" });

    await result.current.uploadImage.mutateAsync({ kind, file });

    expect(apiClient.upload).toHaveBeenCalledWith(`/admin/settings/${kind}`, file);
    expect(toastSuccess).toHaveBeenCalled();
  });

  it.each(["logo", "favicon"] as const)("clears the %s back to the built-in", async (kind) => {
    const result = await loaded();

    await result.current.clearImage.mutateAsync(kind);

    expect(apiClient.delete).toHaveBeenCalledWith(`/admin/settings/${kind}`);
    expect(toastSuccess).toHaveBeenCalled();
  });

  it("reports an upload that was refused", async () => {
    vi.mocked(apiClient.upload).mockRejectedValue(new Error("too large"));
    const result = await loaded();
    const file = new File(["x"], "mark.png", { type: "image/png" });

    await expect(result.current.uploadImage.mutateAsync({ kind: "logo", file })).rejects.toThrow();
    expect(toastError).toHaveBeenCalled();
  });

  it("reports a clear that was refused", async () => {
    vi.mocked(apiClient.delete).mockRejectedValue(new Error("nope"));
    const result = await loaded();

    await expect(result.current.clearImage.mutateAsync("favicon")).rejects.toThrow();
    expect(toastError).toHaveBeenCalled();
  });
});

describe("refetching", () => {
  it("reads the row again, which is what a failed load offers", async () => {
    vi.clearAllMocks();
    vi.mocked(apiClient.get).mockResolvedValue(SETTINGS);
    const result = await loaded();

    await result.current.refetch();

    expect(apiClient.get).toHaveBeenCalledTimes(2);
  });
});
