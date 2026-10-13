import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api-error";
import { unlockPublicArtifact } from "./public-artifact-api";

function answer(status: number, body: unknown): Response {
  return new Response(body === undefined ? "not json" : JSON.stringify(body), { status });
}

describe("unlockPublicArtifact", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("posts the password for this link to the API and returns the opened page", async () => {
    const opened = { password_required: false, title: "Weekly", published_at: "", view: {} };
    const fetchMock = vi.fn().mockResolvedValue(answer(200, opened));
    vi.stubGlobal("fetch", fetchMock);

    await expect(unlockPublicArtifact("https://api.example", "k/1", "hunter22")).resolves.toEqual(
      opened,
    );
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("https://api.example/api/v1/public/artifacts/k%2F1/unlock");
    expect(init.method).toBe("POST");
    expect(init.body).toBe(JSON.stringify({ password: "hunter22" }));
  });

  it("throws the refusal with its status, so the form can tell a wrong password", async () => {
    const refusal = {
      error: { code: "AUTHORIZATION_ERROR", message: "That password is not right." },
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(answer(403, refusal)));

    const failure = await unlockPublicArtifact("https://api.example", "k", "nope").catch(
      (error: unknown) => error,
    );
    expect(failure).toBeInstanceOf(ApiError);
    expect((failure as ApiError).status).toBe(403);
  });

  it("still throws when the answer is not JSON at all", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(answer(502, undefined)));
    await expect(unlockPublicArtifact("https://api.example", "k", "x")).rejects.toBeInstanceOf(
      ApiError,
    );
  });
});
