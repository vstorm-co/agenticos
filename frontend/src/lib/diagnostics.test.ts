import { afterEach, describe, expect, it, vi } from "vitest";
import { apiClient } from "@/lib/api-client";
import { sendPresence } from "./diagnostics";

vi.mock("@/lib/api-client", () => ({ apiClient: { post: vi.fn() } }));
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
const event = {
  signature: "s".repeat(88),
  payload: {
    protocol: 1,
    kind: "presence",
    instance_id: "a".repeat(64),
    event_id: "b".repeat(32),
    at: 123,
    user_id: "c".repeat(64),
    surface: "web",
    expires_at: 183,
  },
};

describe("signed diagnostic presence", () => {
  it("does not send cookies, referrers or account data to the collector", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({
      endpoint: "http://localhost:8010/v1/presence",
      event,
    });
    const fetch = vi.fn().mockResolvedValue(new Response(null, { status: 200 }));
    vi.stubGlobal("fetch", fetch);
    const signal = new AbortController().signal;
    expect(await sendPresence("web", "http://localhost:8010", signal)).toBe("sent");
    expect(apiClient.post).toHaveBeenCalledWith(
      "/diagnostics/presence",
      { surface: "web" },
      { signal },
    );
    expect(fetch).toHaveBeenCalledWith(
      new URL("http://localhost:8010/v1/presence"),
      expect.objectContaining({
        credentials: "omit",
        referrerPolicy: "no-referrer",
        redirect: "error",
        body: JSON.stringify(event),
      }),
    );
  });

  it("makes no external request when disabled or a session is cancelled", async () => {
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    vi.mocked(apiClient.post).mockResolvedValue(null);
    expect(await sendPresence("web", "http://localhost:8010", new AbortController().signal)).toBe(
      "waiting",
    );
    vi.mocked(apiClient.post).mockResolvedValue({
      endpoint: "http://localhost:8010/v1/presence",
      event,
    });
    const controller = new AbortController();
    controller.abort();
    expect(await sendPresence("web", "http://localhost:8010", controller.signal)).toBe("waiting");
    expect(fetch).not.toHaveBeenCalled();
  });

  it.each([
    "https://other.example/v1/presence",
    "http://localhost:8010/private",
    "http://localhost:8010/v1/presence?account=secret",
    "http://user:secret@localhost:8010/v1/presence",
  ])("refuses an unexpected collector endpoint: %s", async (endpoint) => {
    vi.mocked(apiClient.post).mockResolvedValue({ endpoint, event });
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    await expect(
      sendPresence("web", "http://localhost:8010", new AbortController().signal),
    ).rejects.toThrow("Unexpected diagnostic");
    expect(fetch).not.toHaveBeenCalled();
  });

  it("reports collector rejection instead of claiming delivery", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({
      endpoint: "http://localhost:8010/v1/presence",
      event,
    });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 503 })));
    await expect(
      sendPresence("web", "http://localhost:8010", new AbortController().signal),
    ).rejects.toThrow("not accepted");
  });
});
