// @vitest-environment node
import { afterEach, expect, it, vi } from "vitest";

import { GET } from "./route";

afterEach(() => vi.unstubAllEnvs());

it("reports this compiled frontend identity without allowing caches to retain it", async () => {
  vi.stubEnv("NEXT_PUBLIC_APP_BUILD_ID", "deployed-build");
  const response = GET();

  expect(response.status).toBe(200);
  expect(await response.json()).toEqual({ buildId: "deployed-build" });
  expect(response.headers.get("Cache-Control")).toBe("no-store, max-age=0");
});

it("reports an absent build identity as unknown rather than fabricating an update", async () => {
  vi.stubEnv("NEXT_PUBLIC_APP_BUILD_ID", undefined);
  expect(await GET().json()).toEqual({ buildId: null });
});
