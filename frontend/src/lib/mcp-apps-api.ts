/**
 * The MCP Apps page a tool call is shown with, and the calls it makes back (#3450).
 *
 * A page runs in an opaque-origin sandbox with no network, so everything it asks
 * of its server comes through here: the backend checks each request against the
 * call it belongs to - who may read the conversation, the run's tools and
 * approvals, the connection as it is now - and relays it with the connection's
 * credential, which never reaches the browser.
 */

import { apiClient } from "./api-client";

/** What the console has of a call's page: where it is, and what the call was. */
export interface McpAppData {
  /** The page's `ui://` address on its server. */
  resource_uri: string;
  /** The arguments the model called the tool with. */
  tool_input: Record<string, unknown>;
  /** The server's `CallToolResult`, in MCP wire form. */
  result: Record<string, unknown>;
}

function root(conversationId: string, toolCallId: string): string {
  return `/conversations/${conversationId}/tool-calls/${encodeURIComponent(toolCallId)}/app`;
}

/** A signed address to frame the call's page from, good for a few minutes. */
export async function mcpAppFrameUrl(conversationId: string, toolCallId: string): Promise<string> {
  const { url } = await apiClient.post<{ url: string }>(root(conversationId, toolCallId));
  return url;
}

/** A page's `tools/call`, relayed: the server's `CallToolResult`, `isError` included. */
export function mcpAppCallTool(
  conversationId: string,
  toolCallId: string,
  name: string,
  args: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  return apiClient.post(`${root(conversationId, toolCallId)}/tools-call`, {
    name,
    arguments: args,
  });
}

/** A page's `resources/read` of a `ui://` resource on its server. */
export function mcpAppReadResource(
  conversationId: string,
  toolCallId: string,
  uri: string,
): Promise<Record<string, unknown>> {
  return apiClient.post(`${root(conversationId, toolCallId)}/resources-read`, { uri });
}
