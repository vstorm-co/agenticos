import { Plug, Repeat } from "lucide-react";
import { describe, expect, it } from "vitest";

import { brandForUrl, consolePageIcon, hostOf, isAppLink } from "./link-brands";

const ORIGIN = "https://agents.example.com";

/** A console page an agent links to wears the sidebar's mark for it (#2301). */
describe("the console page behind a link", () => {
  it("draws the section's icon for a relative link, its query and anchor aside", () => {
    expect(consolePageIcon("/routines?highlight=routines-create", ORIGIN)).toBe(Repeat);
    expect(consolePageIcon("/mcp-servers?highlight=mcp-add", ORIGIN)).toBe(Plug);
  });

  it("draws nothing for another site, a protocol-relative address or a page outside every section", () => {
    expect(consolePageIcon("https://example.org/routines", ORIGIN)).toBeNull();
    expect(consolePageIcon("//evil.example/routines", ORIGIN)).toBeNull();
    expect(consolePageIcon("/settings/profile", ORIGIN)).toBeNull();
  });
});

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

/** The console's own apps, which an agent links to after publishing one. */
describe("an app's link", () => {
  const origin = "http://localhost:3000";
  const id = "866b63c3-92b5-4ac7-82b9-8e97b6f09b9f";

  it("is an app's page on this console, absolute or not, with its query", () => {
    expect(isAppLink(`${origin}/apps/${id}?org=abc`, origin)).toBe(true);
    expect(isAppLink(`/apps/${id}`, origin)).toBe(true);
  });

  it("is not the apps list, another site's apps, or nonsense", () => {
    expect(isAppLink(`${origin}/apps`, origin)).toBe(false);
    expect(isAppLink(`https://elsewhere.example/apps/${id}`, origin)).toBe(false);
    expect(isAppLink("http://[bad", origin)).toBe(false);
  });
});
