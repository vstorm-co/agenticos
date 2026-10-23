/**
 * @vitest-environment node
 *
 * A server route: it runs where a browser global would be a lie.
 */
import { NextRequest } from "next/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

const revalidateTag = vi.fn();
const forward = vi.fn();

vi.mock("next/cache", () => ({ revalidateTag: (...args: unknown[]) => revalidateTag(...args) }));
vi.mock("@/lib/platform-proxy", () => ({
  platformProxy: () => ({
    GET: forward,
    POST: forward,
    PUT: forward,
    PATCH: forward,
    DELETE: forward,
  }),
}));

const route = await import("./route");

function request(method: string): NextRequest {
  return new NextRequest("http://localhost:3000/api/admin/settings", { method });
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("the deployment settings proxy", () => {
  it.each(["POST", "PUT", "PATCH", "DELETE"] as const)(
    "expires the cached branding after a %s that succeeded",
    async (method) => {
      forward.mockResolvedValue(new Response(null, { status: 200 }));

      await route[method](request(method));

      expect(revalidateTag).toHaveBeenCalledWith("branding", { expire: 0 });
    },
  );

  it("leaves it alone for a refused write and for a read", async () => {
    forward.mockResolvedValue(new Response(null, { status: 403 }));
    await route.PATCH(request("PATCH"));
    forward.mockResolvedValue(new Response(null, { status: 200 }));
    await route.GET(request("GET"));

    expect(revalidateTag).not.toHaveBeenCalled();
  });
});
