/**
 * @vitest-environment node
 */
import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { POST } from "./route";

function post(token: string, body: unknown) {
  return POST(
    new NextRequest(`http://localhost:3000/api/forms/${token}`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
    { params: Promise.resolve({ token }) },
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("POST /api/forms/[token]", () => {
  it("passes the answers to the form's API and its answer back", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify({ message: "Thanks" }), { status: 201 }));
    vi.stubGlobal("fetch", fetchMock);

    const response = await post("tok_1-A", { values: { name: "Ada" }, website: null });

    expect(response.status).toBe(201);
    expect(await response.json()).toEqual({ message: "Thanks" });
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toBe("http://localhost:8000/api/v1/public/workflow-forms/tok_1-A");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ values: { name: "Ada" }, website: null });
  });

  it("passes a refusal back as it came", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: {} }), { status: 422 })),
    );
    expect((await post("tok", { values: {} })).status).toBe(422);
  });

  it("never sends a link this deployment could not have made, and says so on an outage", async () => {
    const fetchMock = vi.fn().mockRejectedValue(new Error("down"));
    vi.stubGlobal("fetch", fetchMock);

    expect((await post("../admin", {})).status).toBe(404);
    expect(fetchMock).not.toHaveBeenCalled();
    expect((await post("tok", {})).status).toBe(502);
  });
});
