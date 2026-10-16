import { describe, expect, it } from "vitest";

import { mcpSnippet } from "./mcp-snippets";

const URL = "https://os.example.com/mcp";

describe("mcpSnippet", () => {
  it("adds Claude Code over HTTP, with the key as a header only when asked", () => {
    expect(mcpSnippet("claude-code", "browser", URL)).toBe(
      "claude mcp add --transport http agenticos https://os.example.com/mcp",
    );
    expect(mcpSnippet("claude-code", "key", URL)).toBe(
      'claude mcp add --transport http agenticos https://os.example.com/mcp \\\n  --header "Authorization: Bearer $AGENTICOS_API_KEY"',
    );
  });

  it("adds Codex and signs it in, or hands it the key's variable", () => {
    expect(mcpSnippet("codex", "browser", URL)).toBe(
      "codex mcp add agenticos --url https://os.example.com/mcp\ncodex mcp login agenticos",
    );
    expect(mcpSnippet("codex", "key", URL)).toBe(
      "codex mcp add agenticos --url https://os.example.com/mcp --bearer-token-env-var AGENTICOS_API_KEY",
    );
  });

  it("has no snippet for Claude Desktop, which is set up in its own settings", () => {
    expect(mcpSnippet("claude-desktop", "browser", URL)).toBeNull();
    expect(mcpSnippet("claude-desktop", "key", URL)).toBeNull();
  });

  it("writes Cursor's and VS Code's config files", () => {
    expect(JSON.parse(mcpSnippet("cursor", "browser", URL)!)).toEqual({
      mcpServers: { agenticos: { url: URL } },
    });
    expect(JSON.parse(mcpSnippet("cursor", "key", URL)!).mcpServers.agenticos.headers).toEqual({
      Authorization: "Bearer aos_…",
    });
    expect(JSON.parse(mcpSnippet("vscode", "browser", URL)!)).toEqual({
      servers: { agenticos: { type: "http", url: URL } },
    });
    const withKey = JSON.parse(mcpSnippet("vscode", "key", URL)!);
    expect(withKey.inputs[0]).toMatchObject({ id: "agenticos-key", password: true });
    expect(withKey.servers.agenticos.headers.Authorization).toBe("Bearer ${input:agenticos-key}");
  });
});
