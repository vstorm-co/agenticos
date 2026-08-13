import { createTranslator } from "next-intl";
import { describe, expect, it } from "vitest";

import messages from "../../messages/en.json";
import type { Translate } from "./agent-step-captions";
import {
  mcpOAuthConnected,
  mcpOAuthMessage,
  mcpOAuthRefused,
  mcpOAuthUpstreamRefusal,
  readMcpOAuthOutcome,
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

  it("shows an upstream refusal as it was written, ampersands and all", () => {
    expect(roundTrip(mcpOAuthUpstreamRefusal("Consent denied by you & your admin"))).toBe(
      "Consent denied by you & your admin",
    );
  });

  it("treats a truncated redirect as an unnamed outcome of its own kind", () => {
    // A stale bookmark or a URL somebody edited. Neither half may throw.
    expect(roundTrip("mcp_oauth=error")).toBe("Sign-in failed, and no connection was saved.");
    expect(roundTrip("mcp_oauth=success")).toBe("The server is connected.");
  });

  it("finds no outcome on a URL that carries none", () => {
    expect(readMcpOAuthOutcome("?name=Linear")).toBeNull();
  });
});
