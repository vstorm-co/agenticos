/** @vitest-environment node */
import { NextRequest } from "next/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { BackendApiError, backendFetch } from "@/lib/server-api";

import { POST } from "./route";

vi.mock("@/lib/server-api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/server-api")>("@/lib/server-api");
  return { ...actual, backendFetch: vi.fn() };
});

function request(body: unknown, headers: Record<string, string> = {}) {
  return new NextRequest("http://localhost:3000/api/auth/pair", {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });
}

beforeEach(() => vi.clearAllMocks());

describe("POST /api/auth/pair", () => {
  it("redeems the code under the phone's user agent and sets the session's cookies", async () => {
    vi.mocked(backendFetch)
      .mockResolvedValueOnce({ access_token: "acc", refresh_token: "ref" })
      .mockResolvedValueOnce({ id: "u1" });

    const response = await POST(
      request(
        { code: "c0de", confirmed: true },
        { "user-agent": "AgenticOS iOS", "x-forwarded-for": "10.0.0.9" },
      ),
    );

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ user: { id: "u1" }, access_token: "acc" });
    const [path, init] = vi.mocked(backendFetch).mock.calls[0]!;
    expect(path).toBe("/api/v1/auth/pairing-codes/redeem");
    expect(init?.headers).toMatchObject({
      "User-Agent": "AgenticOS iOS",
      "x-forwarded-for": "10.0.0.9",
    });
    const cookies = response.headers.getSetCookie().join("\n");
    expect(response.cookies.getAll().map((cookie) => cookie.name)).toEqual([
      "agenticos_access_token",
      "agenticos_refresh_token",
    ]);
    expect(response.cookies.get("agenticos_refresh_token")).toMatchObject({
      value: "ref",
      httpOnly: true,
      maxAge: 604800,
    });
    expect(cookies).toContain("agenticos_access_token=acc");
  });

  it("refuses a request with no code before asking the backend", async () => {
    const response = await POST(request({}));
    expect(response.status).toBe(400);
    expect(backendFetch).not.toHaveBeenCalled();
    expect((await POST(request({ code: "c0de" }))).status).toBe(400);
    expect(backendFetch).not.toHaveBeenCalled();
  });

  it("passes a spent code's refusal, a rate limit, and a failure through as refusals", async () => {
    vi.mocked(backendFetch).mockRejectedValueOnce(
      new BackendApiError(401, "Unauthorized", { detail: "expired" }),
    );
    expect((await POST(request({ code: "x", confirmed: true }))).status).toBe(401);
    vi.mocked(backendFetch).mockRejectedValueOnce(new BackendApiError(429, "Too Many", {}));
    expect((await POST(request({ code: "x", confirmed: true }, { "user-agent": "" }))).status).toBe(
      429,
    );
    vi.mocked(backendFetch).mockRejectedValueOnce(new Error("down"));
    expect((await POST(request({ code: "x", confirmed: true }))).status).toBe(500);
  });
});
