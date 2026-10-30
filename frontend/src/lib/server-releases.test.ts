// @vitest-environment node
import { afterEach, expect, it, vi } from "vitest";
vi.mock("next/cache", () => ({ unstable_cache: (fn: () => Promise<unknown>) => fn }));
import { fetchCurrentRelease, fetchLatestRelease } from "./server-releases";
import { GET } from "@/app/api/releases/latest/route";

it("does not query a release tag for a development-only version", async () => {
  vi.resetModules();
  vi.doMock("../../package.json", () => ({ version: "development" }));
  try {
    const { fetchCurrentRelease: read } = await import("./server-releases");
    expect(await read()).toEqual({ ok: true, release: null });
  } finally {
    vi.doUnmock("../../package.json");
    vi.resetModules();
  }
});

const released = { tag_name: "v1.29.0", draft: false, prerelease: false };
afterEach(() => vi.unstubAllGlobals());
function reply(payload: unknown, status = 200) {
  const fetcher = vi
    .fn()
    .mockImplementation(async () => new Response(JSON.stringify(payload), { status }));
  vi.stubGlobal("fetch", fetcher);
  return fetcher;
}
it("checks only public stable metadata and builds the release URL on the fixed official repository", async () => {
  const fetcher = reply({ ...released, html_url: "https://untrusted.example" });
  expect(await fetchLatestRelease()).toEqual({
    ok: true,
    latest: {
      version: "1.29.0",
      url: "https://github.com/vstorm-co/agenticos/releases/tag/v1.29.0",
    },
  });
  expect(fetcher).toHaveBeenCalledWith(
    "https://api.github.com/repos/vstorm-co/agenticos/releases/latest",
    expect.objectContaining({
      credentials: "omit",
      cache: "no-store",
      signal: expect.any(AbortSignal),
    }),
  );
});
it.each([403, 429, 500])("reports HTTP %s as unavailable", async (status) => {
  reply({}, status);
  expect(await fetchLatestRelease()).toEqual({ ok: false });
});
it("allows no published public release without inventing a version", async () => {
  reply({}, 404);
  expect(await fetchLatestRelease()).toEqual({ ok: true, latest: null });
});
it.each([
  {},
  { ...released, tag_name: "not-a-version" },
  { ...released, draft: true },
  { ...released, prerelease: true },
  { ...released, tag_name: "v1.30.0-beta.1" },
])("rejects malformed or non-stable releases", async (payload) => {
  reply(payload);
  expect(await fetchLatestRelease()).toEqual({ ok: false });
});
it.each([
  new TypeError("network"),
  new SyntaxError("invalid JSON"),
  new DOMException("deadline", "TimeoutError"),
])("reports expected transport failures without claiming the app is up to date", async (error) => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(error));
  expect(await fetchLatestRelease()).toEqual({ ok: false });
});
it("does not disguise an unexpected implementation error", async () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("bug")));
  await expect(fetchLatestRelease()).rejects.toThrow("bug");
});
it("serves the public contract through the BFF", async () => {
  reply(released);
  const response = await GET();
  expect(response.status).toBe(200);
  expect(await response.json()).toEqual({
    latest: {
      version: "1.29.0",
      url: "https://github.com/vstorm-co/agenticos/releases/tag/v1.29.0",
    },
  });
});
it("keeps provider failures distinct from a successful check", async () => {
  reply({}, 429);
  const response = await GET();
  expect(response.status).toBe(503);
  expect(await response.json()).toEqual({ code: "RELEASE_CHECK_UNAVAILABLE" });
});

import { version } from "../../package.json";
import { GET as currentGET } from "@/app/api/releases/current/route";
it("loads notes for the installed release, never the latest uninstalled version", async () => {
  const fetcher = reply({ ...released, tag_name: `v${version}`, body: "## Added\nNew features" });
  expect(await fetchCurrentRelease()).toEqual({
    ok: true,
    release: {
      version,
      url: `https://github.com/vstorm-co/agenticos/releases/tag/v${version}`,
      body: "## Added\nNew features",
    },
  });
  expect(fetcher.mock.calls[0]?.[0]).toBe(
    `https://api.github.com/repos/vstorm-co/agenticos/releases/tags/v${version}`,
  );
  expect((await currentGET()).status).toBe(200);
});
it.each([undefined, null, "", "   "])("omits empty release notes (%s)", async (body) => {
  reply({ ...released, tag_name: `v${version}`, body });
  expect(await fetchCurrentRelease()).toEqual({ ok: true, release: null });
});
it("rejects notes from a different release", async () => {
  reply({ ...released, tag_name: "v99.0.0", body: "Wrong release" });
  expect(await fetchCurrentRelease()).toEqual({ ok: false });
});
it("returns an explicit unavailable response for a failed notes check", async () => {
  reply({}, 429);
  expect((await currentGET()).status).toBe(503);
});
