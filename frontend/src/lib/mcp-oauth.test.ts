import { createTranslator } from "next-intl";
import { describe, expect, it } from "vitest";

import messages from "../../messages/en.json";
import type { Translate } from "./agent-step-captions";
import {
  hereForMcpOAuthReturn,
  mcpOAuthConnected,
  mcpOAuthMessage,
  mcpOAuthRefused,
  mcpOAuthUpstreamRefusal,
  readMcpOAuthOutcome,
  rememberMcpOAuthReturn,
  safeMcpOAuthReturn,
} from "./mcp-oauth";

/**
 * The real `mcp` messages, so a test asserts the sentence a person reads.
 *
 * Cast because `createTranslator` types its key against the message tree while
 * `Translate` takes the string a module table holds.
 */
const t = createTranslator({ locale: "en", messages, namespace: "mcp" }) as Translate;

/** What the reader makes of what the writer wrote - the drift #657 was. */
function roundTrip(query: string) {
  const outcome = readMcpOAuthOutcome(`?${query}`);
  return outcome === null ? null : mcpOAuthMessage(outcome, t);
}

describe("the MCP OAuth callback query", () => {
  it("carries a connection name through a redirect intact", () => {
    expect(roundTrip(mcpOAuthConnected("Linear Work"))).toBe("Linear Work is connected.");
  });

  it("says the server is connected when the backend named nothing", () => {
    expect(roundTrip(mcpOAuthConnected(""))).toBe("The server is connected.");
  });

  it("resolves each refusal this repository writes into copy", () => {
    expect(roundTrip(mcpOAuthRefused("AUTHORIZATION_FAILED"))).toBe(
      "Sign-in failed, and no connection was saved.",
    );
    expect(roundTrip(mcpOAuthRefused("MISSING_AUTHORIZATION_CODE"))).toBe(
      "The provider sent no authorization code.",
    );
  });

  it("quotes an upstream refusal after a refusal of its own", () => {
    expect(roundTrip(mcpOAuthUpstreamRefusal("Consent denied by you & your admin"))).toBe(
      "Sign-in failed, and no connection was saved — Consent denied by you & your admin",
    );
  });

  it("treats a truncated redirect as an unnamed outcome of its own kind", () => {
    // A stale bookmark, or a URL somebody edited. Neither half may throw.
    expect(roundTrip("mcp_oauth=error")).toBe("Sign-in failed, and no connection was saved.");
    expect(roundTrip("mcp_oauth=success")).toBe("The server is connected.");
  });

  it("finds no outcome on a URL that carries none", () => {
    expect(readMcpOAuthOutcome("?mcp_oauth_name=Linear")).toBeNull();
    expect(readMcpOAuthOutcome("?mcp_oauth=")).toBeNull();
  });
});

/**
 * What a stranger can put on this URL.
 *
 * The callback authenticates on the `state` token and takes no session, so the
 * address is reachable by anybody with a link - and #657 is what promoted its
 * query from something nobody read into a native product toast. These are the
 * two properties that keeps honest.
 */
describe("a refusal written by somebody else", () => {
  it("cannot spell one of this repository's own codes", () => {
    // Hand-crafted: the writer never puts a code in the detail parameter, and a
    // toast in the product's own voice is exactly what a link should not buy.
    expect(roundTrip("mcp_oauth=error&mcp_oauth_detail=AUTHORIZATION_FAILED")).toBe(
      "Sign-in failed, and no connection was saved — AUTHORIZATION_FAILED",
    );
    expect(roundTrip("mcp_oauth=error&mcp_oauth_failure=NOT_A_CODE")).toBe(
      "Sign-in failed, and no connection was saved.",
    );
  });

  it("reaches the toast as one line, capped, and never empty", () => {
    const outcome = readMcpOAuthOutcome(
      `?${mcpOAuthUpstreamRefusal(`Re-authenticate\n\nat evil.example ${"x".repeat(400)}`)}`,
    );

    expect(outcome).toMatchObject({ status: "upstream-error" });
    const detail = outcome as { detail: string };
    expect(detail.detail).toHaveLength(200);
    expect(detail.detail).not.toContain("\n");

    // Whitespace and control characters alone are not a reason at all.
    expect(roundTrip(mcpOAuthUpstreamRefusal(" \n\t "))).toBe(
      "Sign-in failed, and no connection was saved.",
    );
  });
});

describe("where the consent comes back to", () => {
  it("accepts one of this app's own paths, query included", () => {
    expect(safeMcpOAuthReturn(encodeURIComponent("/chat?id=abc"))).toBe("/chat?id=abc");
  });

  it("falls back to the servers page when nothing was remembered", () => {
    expect(safeMcpOAuthReturn(undefined)).toBeNull();
  });

  it.each(["//evil.example/x", "https://evil.example", "/\\evil.example", "chat"])(
    "refuses %s, because a cookie is the browser's to set",
    (raw) => {
      expect(safeMcpOAuthReturn(encodeURIComponent(raw))).toBeNull();
    },
  );

  it("writes a short-lived, path-wide cookie", () => {
    rememberMcpOAuthReturn("/chat?id=abc");

    expect(document.cookie).toContain(`mcp_oauth_return=${encodeURIComponent("/chat?id=abc")}`);
  });
});

describe("hereForMcpOAuthReturn", () => {
  it("names this page, query included", () => {
    window.history.replaceState({}, "", "/chat?id=abc");

    expect(hereForMcpOAuthReturn()).toBe("/chat?id=abc");
  });
});
