import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiClient } from "./api-client";
import { useAuthStore, useOrgStore } from "@/stores";

/**
 * Every request the browser makes.
 *
 * Four things live here and each one has bitten this app: requests go to
 * `/api/*` rather than to the platform, so the backend URL never reaches the
 * browser; the active organization travels on every request, so an org-scoped
 * endpoint resolves the tenant the UI is showing; a 401 is recovered once by
 * refreshing, and a burst of them shares one refresh; and a multipart body is
 * sent without a `Content-Type`, because only the browser knows the boundary.
 */
function ok(body: unknown = { ok: true }, status = 200) {
  return {
    ok: status < 400,
    status,
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(body === null ? "" : JSON.stringify(body)),
  } as Response;
}

function refused(status: number, body: unknown) {
  return {
    ok: false,
    status,
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  } as Response;
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn().mockResolvedValue(ok());
  vi.stubGlobal("fetch", fetchMock);
  useOrgStore.setState({ activeOrgId: null });
  useAuthStore.setState({ accessToken: null });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

/** The init object of the nth fetch call. */
function init(nth = 0): RequestInit {
  return fetchMock.mock.calls[nth]![1] as RequestInit;
}

function headers(nth = 0): Record<string, string> {
  return init(nth).headers as Record<string, string>;
}

describe("apiClient", () => {
  it("addresses this app's own proxy, never the platform", () => {
    // The whole reason the client exists: the backend URL is a server secret.
    return apiClient.get("/agents").then(() => {
      expect(fetchMock.mock.calls[0]![0]).toBe("/api/agents");
    });
  });

  it("sends each verb with its own body handling", async () => {
    await apiClient.get("/agents");
    await apiClient.post("/agents", { name: "Support" });
    await apiClient.put("/agents/a1/sharing/grants", { level: "read" });
    await apiClient.patch("/agents/a1", { name: "Sales" });
    await apiClient.delete("/agents/a1");

    expect(fetchMock.mock.calls.map((call) => (call[1] as RequestInit).method)).toEqual([
      "GET",
      "POST",
      "PUT",
      "PATCH",
      "DELETE",
    ]);
    expect(init(1).body).toBe(JSON.stringify({ name: "Support" }));
    expect(init(0).body).toBeUndefined();
  });

  it("appends query parameters rather than expecting callers to build a URL", async () => {
    await apiClient.get("/runs", { params: { agent_id: "a1", days: "7" } });

    expect(fetchMock.mock.calls[0]![0]).toBe("/api/runs?agent_id=a1&days=7");
  });

  it("carries the active organization on every request", async () => {
    // An org-scoped endpoint resolves the tenant from this header; without it the
    // request falls back to the caller's personal organization and reads the
    // wrong rows.
    useOrgStore.setState({ activeOrgId: "org-7" });

    await apiClient.get("/agents");

    expect(headers()["X-Organization-Id"]).toBe("org-7");
  });

  it("sends no organization header when none is chosen", async () => {
    // Rather than an empty one, which the server would try to resolve.
    await apiClient.get("/agents");

    expect(headers()).not.toHaveProperty("X-Organization-Id");
  });

  it("lets a caller add headers without losing the ones it sets", async () => {
    useOrgStore.setState({ activeOrgId: "org-7" });

    await apiClient.get("/agents", { headers: { "X-Trace": "t1" } });

    expect(headers()).toMatchObject({ "X-Trace": "t1", "X-Organization-Id": "org-7" });
  });

  it("reads an empty body as null rather than failing to parse it", async () => {
    // A 204 from a DELETE is the common case.
    fetchMock.mockResolvedValue(ok(null, 204));

    await expect(apiClient.delete("/agents/a1")).resolves.toBeNull();
  });

  it("raises the server's own sentence, with its status and payload", async () => {
    fetchMock.mockResolvedValue(
      refused(409, {
        error: { code: "ALREADY_EXISTS", message: "That handle is taken", details: { slug: "s" } },
      }),
    );

    await expect(apiClient.post("/agents", {})).rejects.toMatchObject({
      status: 409,
      message: "That handle is taken",
      code: "ALREADY_EXISTS",
      details: { slug: "s" },
    });
  });

  it("still raises when the refusal is not JSON at all", async () => {
    // A proxy timeout answers with HTML; the status is still worth surfacing.
    fetchMock.mockResolvedValue({
      ok: false,
      status: 504,
      json: () => Promise.reject(new Error("not json")),
      text: () => Promise.resolve(""),
    } as Response);

    const failure = await apiClient.get("/agents").catch((error: unknown) => error);

    expect(failure).toBeInstanceOf(ApiError);
    expect((failure as ApiError).status).toBe(504);
  });
});

describe("recovering from an expired token", () => {
  it("refreshes once and retries the request", async () => {
    fetchMock
      .mockResolvedValueOnce(refused(401, { detail: "Token expired" }))
      .mockResolvedValueOnce(ok({ access_token: "fresh" }))
      .mockResolvedValueOnce(ok({ items: [] }));

    await expect(apiClient.get("/agents")).resolves.toEqual({ items: [] });

    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      "/api/agents",
      "/api/auth/refresh",
      "/api/agents",
    ]);
  });

  it("keeps the fresh token in memory, which is what the websocket authenticates with", async () => {
    fetchMock
      .mockResolvedValueOnce(refused(401, {}))
      .mockResolvedValueOnce(ok({ access_token: "fresh" }))
      .mockResolvedValueOnce(ok({}));

    await apiClient.get("/agents");

    expect(useAuthStore.getState().accessToken).toBe("fresh");
  });

  it("shares one refresh across a burst of concurrent 401s", async () => {
    // Six panels mount at once on a page load with an expired token. Six
    // refreshes would rotate the cookie six times and lose five of them.
    fetchMock.mockImplementation((url: string) => {
      if (url === "/api/auth/refresh") return Promise.resolve(ok({ access_token: "fresh" }));
      return Promise.resolve(
        fetchMock.mock.calls.filter((call) => call[0] !== "/api/auth/refresh").length <= 3
          ? refused(401, {})
          : ok({ items: [] }),
      );
    });

    await Promise.all([apiClient.get("/a"), apiClient.get("/b"), apiClient.get("/c")]);

    const refreshes = fetchMock.mock.calls.filter((call) => call[0] === "/api/auth/refresh");
    expect(refreshes).toHaveLength(1);
  });

  it("surfaces the original 401 when the refresh is itself refused", async () => {
    fetchMock
      .mockResolvedValueOnce(refused(401, { detail: "Token expired" }))
      .mockResolvedValueOnce(refused(401, { detail: "No refresh cookie" }));

    await expect(apiClient.get("/agents")).rejects.toMatchObject({
      status: 401,
      message: "Token expired",
    });
  });

  it("survives a refresh whose body is not JSON, because the cookie still rotated", async () => {
    fetchMock
      .mockResolvedValueOnce(refused(401, {}))
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: () => Promise.reject(new Error("not json")),
        text: () => Promise.resolve(""),
      } as Response)
      .mockResolvedValueOnce(ok({ items: [] }));

    await expect(apiClient.get("/agents")).resolves.toEqual({ items: [] });
  });

  it("survives a refresh that answers with nothing to set", async () => {
    fetchMock
      .mockResolvedValueOnce(refused(401, {}))
      .mockResolvedValueOnce(ok({}))
      .mockResolvedValueOnce(ok({ items: [] }));

    await apiClient.get("/agents");

    expect(useAuthStore.getState().accessToken).toBeNull();
  });

  it("treats a refresh that could not be reached as a failed one", async () => {
    fetchMock
      .mockResolvedValueOnce(refused(401, { detail: "Token expired" }))
      .mockRejectedValueOnce(new Error("offline"));

    await expect(apiClient.get("/agents")).rejects.toMatchObject({ status: 401 });
  });

  it("does not replay the request when the refresh says the impersonation is over", async () => {
    // The request was made as the account being acted as. Replaying it with the
    // token a refresh would mint runs it as the administrator (#1044). The 401
    // surfaces instead, and the store is told so the banner can take the exit.
    useAuthStore.setState({ impersonationRevoked: false });
    fetchMock
      .mockResolvedValueOnce(refused(401, { detail: "Impersonation has ended" }))
      .mockResolvedValueOnce(refused(401, { code: "IMPERSONATION_ENDED" }));

    await expect(apiClient.post("/agents", { name: "x" })).rejects.toMatchObject({
      status: 401,
      message: "Impersonation has ended",
    });

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(useAuthStore.getState().impersonationRevoked).toBe(true);
  });

  it("does not raise the flag for a refusal that is about something else", async () => {
    useAuthStore.setState({ impersonationRevoked: false });
    fetchMock
      .mockResolvedValueOnce(refused(401, {}))
      .mockResolvedValueOnce(refused(401, { code: "NO_REFRESH_TOKEN" }))
      .mockResolvedValueOnce(refused(401, {}))
      .mockResolvedValueOnce(refused(503, { code: "IMPERSONATION_ENDED" }))
      .mockResolvedValueOnce(refused(401, {}))
      .mockResolvedValueOnce({
        ok: false,
        status: 401,
        json: () => Promise.reject(new Error("not json")),
        text: () => Promise.resolve(""),
      } as Response);

    await expect(apiClient.get("/a")).rejects.toMatchObject({ status: 401 });
    await expect(apiClient.get("/b")).rejects.toMatchObject({ status: 401 });
    await expect(apiClient.get("/c")).rejects.toMatchObject({ status: 401 });

    expect(useAuthStore.getState().impersonationRevoked).toBe(false);
  });

  it("never refreshes in response to the refresh route's own 401", async () => {
    // Which would recurse until the stack gave out.
    fetchMock.mockResolvedValue(refused(401, { detail: "No refresh cookie" }));

    await expect(apiClient.post("/auth/refresh")).rejects.toMatchObject({ status: 401 });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});

describe("uploading", () => {
  it("sends one file as multipart, with no Content-Type of its own", async () => {
    // Only the browser knows the boundary it generated; setting the header by
    // hand drops it and FastAPI rejects the body it was just handed.
    await apiClient.upload("/agents/a1/avatar", new File(["x"], "face.png"));

    expect(headers()).not.toHaveProperty("Content-Type");
    expect(init().body).toBeInstanceOf(FormData);
  });

  it("keeps the organization header on an upload, and the 401 recovery with it", async () => {
    useOrgStore.setState({ activeOrgId: "org-7" });
    fetchMock
      .mockResolvedValueOnce(refused(401, {}))
      .mockResolvedValueOnce(ok({ access_token: "fresh" }))
      .mockResolvedValueOnce(ok({ id: "a1" }));

    await apiClient.upload("/agents/a1/avatar", new File(["x"], "face.png"));

    expect(headers()["X-Organization-Id"]).toBe("org-7");
    expect(headers(2)["X-Organization-Id"]).toBe("org-7");
  });

  it("names every file in a multi-upload, so a folder does not arrive flattened", async () => {
    // The name is the resource's path on the other side. Appending the bare
    // `File` would send only the basename and collide `a/x.md` with `b/x.md`.
    const first = new File(["1"], "x.md");
    const second = new File(["2"], "x.md");

    await apiClient.uploadMany("/skills/s1/resources", [first, second], (file) =>
      file === first ? "references/x.md" : "examples/x.md",
    );

    const names = (init().body as FormData).getAll("files").map((entry) => (entry as File).name);
    expect(names).toEqual(["references/x.md", "examples/x.md"]);
  });
});
