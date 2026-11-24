import { describe, expect, it, vi } from "vitest";

import { nextConfig } from "./next.config";

it("uses the same public build identity after config reloads in build workers", async () => {
  const buildId = await nextConfig.generateBuildId?.();
  expect(buildId).toBeTruthy();
  expect(buildId).toBe(process.env.NEXT_PUBLIC_APP_BUILD_ID);

  vi.resetModules();
  const reloaded = await import("./next.config");
  expect(await reloaded.nextConfig.generateBuildId?.()).toBe(buildId);
});

describe("email font response headers", () => {
  it("allows cross-origin font loads only on the public email font path", async () => {
    const rules = await nextConfig.headers?.();
    const emailFontRule = rules?.find((rule) => rule.source === "/fonts/email/:path*");

    expect(emailFontRule?.headers).toEqual([{ key: "Access-Control-Allow-Origin", value: "*" }]);
    expect(
      rules
        ?.filter((rule) => rule.source !== "/fonts/email/:path*")
        .flatMap((rule) => rule.headers)
        .some((header) => header.key.toLowerCase() === "access-control-allow-origin"),
    ).toBe(false);
  });
});
