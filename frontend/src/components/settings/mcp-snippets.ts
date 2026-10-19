/**
 * How each MCP client is pointed at this deployment's own MCP server.
 *
 * Every client speaks streamable HTTP to `<api>/mcp`. Signing in through the
 * browser is the default: the client discovers the OAuth server from the 401's
 * `resource_metadata`, opens the console's consent page and renews its own
 * token. An API key is for a client that cannot open a browser.
 *
 * Everything below is a command or a config file the reader pastes as it is,
 * so none of it is copy to translate.
 */

export const MCP_CLIENTS = ["claude-code", "codex", "claude-desktop", "cursor", "vscode"] as const;
export type McpClient = (typeof MCP_CLIENTS)[number];
export type McpAuth = "browser" | "key";

/** The client's product name - a proper noun, the same in every language. */
export const MCP_CLIENT_NAME: Record<McpClient, string> = {
  // i18n-exempt: product names, the same in every language
  "claude-code": "Claude Code",
  codex: "Codex",
  // i18n-exempt: product names, the same in every language
  "claude-desktop": "Claude Desktop",
  cursor: "Cursor",
  // i18n-exempt: product names, the same in every language
  vscode: "VS Code",
};

const SERVER = "agenticos";
const KEY_VARIABLE = "AGENTICOS_API_KEY";
// i18n-exempt: a placeholder value in the reader's own config file
const KEY_PLACEHOLDER = "Bearer aos_…";
// i18n-exempt: VS Code's input reference syntax, written into the reader's config
const VSCODE_KEY_REFERENCE = "Bearer ${input:agenticos-key}";
// i18n-exempt: the prompt VS Code shows, written into the reader's own config file
const VSCODE_KEY_PROMPT = "AgenticOS API key";

function json(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

function claudeCode(auth: McpAuth, url: string): string {
  const add = ["claude", "mcp", "add", "--transport", "http", SERVER, url].join(" ");
  return auth === "key" ? `${add} \\\n  --header "Authorization: Bearer $${KEY_VARIABLE}"` : add;
}

function codex(auth: McpAuth, url: string): string {
  const add = ["codex", "mcp", "add", SERVER, "--url", url].join(" ");
  return auth === "key"
    ? [add, "--bearer-token-env-var", KEY_VARIABLE].join(" ")
    : [add, ["codex", "mcp", "login", SERVER].join(" ")].join("\n");
}

function cursor(auth: McpAuth, url: string): string {
  const server = auth === "key" ? { url, headers: { Authorization: KEY_PLACEHOLDER } } : { url };
  return json({ mcpServers: { [SERVER]: server } });
}

function vscode(auth: McpAuth, url: string): string {
  if (auth === "browser") return json({ servers: { [SERVER]: { type: "http", url } } });
  return json({
    inputs: [
      { type: "promptString", id: "agenticos-key", description: VSCODE_KEY_PROMPT, password: true },
    ],
    servers: { [SERVER]: { type: "http", url, headers: { Authorization: VSCODE_KEY_REFERENCE } } },
  });
}

/**
 * The command or configuration that connects `client` to `url`, or `null` for a
 * client configured only through its own settings screen (Claude Desktop).
 */
export function mcpSnippet(client: McpClient, auth: McpAuth, url: string): string | null {
  switch (client) {
    case "claude-code":
      return claudeCode(auth, url);
    case "codex":
      return codex(auth, url);
    case "claude-desktop":
      return null;
    case "cursor":
      return cursor(auth, url);
    case "vscode":
      return vscode(auth, url);
  }
}
