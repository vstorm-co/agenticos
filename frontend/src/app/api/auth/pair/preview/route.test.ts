/** @vitest-environment node */
import { NextRequest } from "next/server";
import { beforeEach, expect, it, vi } from "vitest";
import { BackendApiError, backendFetch } from "@/lib/server-api";
import { POST } from "./route";
vi.mock("@/lib/server-api", async () => ({
  ...(await vi.importActual<typeof import("@/lib/server-api")>("@/lib/server-api")),
  backendFetch: vi.fn(),
}));
beforeEach(() => vi.clearAllMocks());
function request(body: unknown) {
  return new NextRequest("http://localhost:3000/api/auth/pair/preview", {
    method: "POST",
    body: JSON.stringify(body),
  });
}
it("previews identity without setting any session cookies", async () => {
  const identity = { id: "u", email: "owner@example.com", full_name: "Owner" };
  vi.mocked(backendFetch).mockResolvedValue(identity);
  const response = await POST(request({ code: "scanned" }));
  expect(await response.json()).toEqual(identity);
  expect(response.headers.getSetCookie()).toEqual([]);
  expect(response.headers.get("cache-control")).toContain("no-store");
  expect(backendFetch).toHaveBeenCalledWith(
    "/api/v1/auth/pairing-codes/preview",
    expect.objectContaining({ body: JSON.stringify({ code: "scanned" }) }),
  );
});
it.each([null, {}, { code: 42 }, { code: "" }])("refuses malformed input %j", async (body) => {
  expect((await POST(request(body))).status).toBe(400);
  expect(backendFetch).not.toHaveBeenCalled();
});
it("preserves expiry, throttling and backend failures without setting cookies", async () => {
  for (const status of [401, 429]) {
    vi.mocked(backendFetch).mockRejectedValueOnce(new BackendApiError(status, "refused", {}));
    const response = await POST(request({ code: "x" }));
    expect(response.status).toBe(status);
    expect(response.headers.getSetCookie()).toEqual([]);
  }
  vi.mocked(backendFetch).mockRejectedValueOnce(new Error("offline"));
  expect((await POST(request({ code: "x" }))).status).toBe(500);
});
