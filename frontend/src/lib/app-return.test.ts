import { describe, expect, it } from "vitest";
import { appLinkFromChat, appReturnTo } from "./app-return";
const chat = "/chat?id=4ce1d419-24c9-4c34-a559-c5b187ecf0de";
describe("App return destinations", () => {
  it("retains the exact conversation and locale, excluding unrelated query parameters", () => {
    expect(appReturnTo(`${chat}&returnTo=https://elsewhere.invalid#section`)).toBe(chat);
    expect(appReturnTo(`/pl${chat}`)).toBe(`/pl${chat}`);
    const link = new URL(appLinkFromChat("/apps/a?version=v", chat), "https://console.invalid");
    expect(link.searchParams.get("version")).toBe("v");
    expect(link.searchParams.get("returnTo")).toBe(chat);
  });
  it.each([
    null,
    undefined,
    "",
    "https://evil.invalid/chat",
    "//evil.invalid/chat",
    "/\\evil.invalid/chat",
    "/apps/a",
    "/chat?id=bad",
    "/chat",
  ])("rejects non-conversation destinations: %s", (value) => {
    expect(appReturnTo(value)).toBeNull();
  });
  it("leaves other routes and links from outside chat alone", () => {
    expect(appLinkFromChat("/agents/a", chat)).toBe("/agents/a");
    expect(appLinkFromChat("/apps/a", "/runs")).toBe("/apps/a");
    expect(appLinkFromChat("https://evil.invalid/apps/a", chat)).toBe(
      "https://evil.invalid/apps/a",
    );
  });
});

it("adds the return destination to model-written absolute App links on this deployment", () => {
  const path = appLinkFromChat(
    "http://localhost:3213/apps/a?org=org",
    chat,
    "http://localhost:3213",
  );
  const parsed = new URL(path, "http://localhost:3213");
  expect(path).toMatch(/^\/apps\/a/);
  expect(parsed.searchParams.get("returnTo")).toBe(chat);
  expect(parsed.searchParams.get("org")).toBe("org");
  expect(appLinkFromChat("http://[", chat)).toBe("http://[");
});
