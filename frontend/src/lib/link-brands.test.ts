import { describe, expect, it } from "vitest";

import { brandForUrl, hostOf } from "./link-brands";

/** Which service a link an agent wrote belongs to - the mark drawn beside it. */
describe("the service behind a link", () => {
  it("finds a page on the domain people link, not the MCP server's host", () => {
    expect(brandForUrl("https://www.notion.so/Roadmap-2b1f")).toBe("notion");
    expect(brandForUrl("https://acme.atlassian.net/browse/OPS-12")).toBe("atlassian");
    expect(brandForUrl("https://docs.google.com/document/d/1")).toBe("gdrive");
  });

  it("matches a whole domain, never a name that only ends the same way", () => {
    expect(brandForUrl("https://notgithub.com/x")).toBeNull();
    expect(brandForUrl("https://example.com/github.com")).toBeNull();
  });

  it("has nothing to say about an address that is not one", () => {
    expect(brandForUrl("not a url")).toBeNull();
    expect(hostOf("not a url")).toBeNull();
    expect(hostOf("https://www.ledgerly.app/pricing")).toBe("ledgerly.app");
  });
});
