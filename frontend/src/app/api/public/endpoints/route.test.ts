import { afterEach, describe, expect, it, vi } from "vitest";

import { GET } from "./route";

describe("the endpoints the desktop app asks for", () => {
  afterEach(() => vi.unstubAllEnvs());

  it("advertises instance session isolation only when configured", async () => {
    vi.stubEnv("SESSION_COOKIE_NAMESPACE", "instance-one");
    expect(await GET().json()).toMatchObject({ session_cookie_namespace: "instance-one" });
  });

  it("names the API and socket origins the console itself uses, uncached", async () => {
    vi.stubEnv("PUBLIC_API_URL", "https://api.acme.test");
    vi.stubEnv("PUBLIC_WS_URL", "wss://api.acme.test");

    const response = GET();

    expect(await response.json()).toEqual({
      api_url: "https://api.acme.test",
      ws_url: "wss://api.acme.test",
    });
    expect(response.headers.get("cache-control")).toBe("no-store");
  });
});
