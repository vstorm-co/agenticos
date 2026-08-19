/**
 * @vitest-environment node
 *
 * This module runs on the server, above `[locale]`, and reaches the backend
 * directly. Running it in a jsdom global would be a lie about where it executes.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { BUILT_IN_BRANDING } from "./branding";
import { readBranding } from "./branding-server";
import { backendFetch } from "./server-api";

vi.mock("./server-api", async () => {
  const actual = await vi.importActual<typeof import("./server-api")>("./server-api");
  return { ...actual, backendFetch: vi.fn() };
});

const fetchBackend = vi.mocked(backendFetch);

afterEach(() => {
  vi.restoreAllMocks();
});

describe("reading the deployment's identity on the server", () => {
  it("resolves what the administrator overrode", async () => {
    fetchBackend.mockResolvedValue({
      app_name: "Acme AI",
      tagline: null,
      description: null,
      logo_version: 7,
      favicon_version: null,
      footer_text: null,
      terms_url: null,
      privacy_url: null,
      signup_mode: "closed",
      allowed_email_domains: [],
      maintenance_mode: false,
      maintenance_message: null,
    });

    const branding = await readBranding();

    expect(branding.appName).toBe("Acme AI");
    expect(branding.logoUrl).toBe("/api/branding/mark/logo?v=7");
    expect(branding.signupMode).toBe("closed");
  });

  it("never caches, so a rename shows on the next page load", async () => {
    // Next would otherwise reuse this answer for the whole lifetime of the build,
    // which reads as a save that did not take.
    fetchBackend.mockResolvedValue(null);

    await readBranding();

    expect(fetchBackend).toHaveBeenCalledWith(
      expect.stringContaining("/branding"),
      expect.objectContaining({ cache: "no-store" }),
    );
  });

  it("falls back to the built-in rather than throwing", async () => {
    // A deployment whose API is down still has to render a sign-in page, and its
    // name is not why anybody is on it.
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    fetchBackend.mockRejectedValue(new Error("connect ECONNREFUSED"));

    await expect(readBranding()).resolves.toEqual(BUILT_IN_BRANDING);
    expect(warn).toHaveBeenCalled();
  });
});
