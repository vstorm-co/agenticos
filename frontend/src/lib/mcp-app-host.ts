/**
 * The host half of MCP Apps (SEP-1865, `io.modelcontextprotocol/ui`, 2026-01-26)
 * for one page: JSON-RPC 2.0 over `postMessage`, with the page in an iframe.
 *
 * Kept free of React and of the DOM so each answer can be tested on its own. The
 * frame (`components/chat/mcp-app-frame.tsx`) owns the iframe and the dialogs;
 * this decides what each message from the page gets back.
 */

import { ApiError } from "./api-error";

export const MCP_APPS_PROTOCOL = "2026-01-26";

export interface JsonRpcMessage {
  jsonrpc: "2.0";
  id?: string | number;
  method?: string;
  params?: Record<string, unknown>;
}

export type JsonRpcReply =
  | { jsonrpc: "2.0"; id: string | number; result: unknown }
  | { jsonrpc: "2.0"; id: string | number; error: { code: number; message: string } };

/** The JSON-RPC codes a host answers with. */
export const METHOD_NOT_FOUND = -32601;
export const INVALID_PARAMS = -32602;
/** The server or the console refused: a relayed call that was not let through. */
export const SERVER_ERROR = -32000;

export interface HostContext {
  theme: "light" | "dark";
  locale: string;
  /** The tool the page is shown for, as the model called it. */
  toolName: string;
}

/** What the host does for a page; the frame supplies each against the backend and the person. */
export interface HostActions {
  callTool: (name: string, args: Record<string, unknown>) => Promise<unknown>;
  readResource: (uri: string) => Promise<unknown>;
  /** Ask the person whether to open a link; resolves once it is asked, not answered. */
  openLink: (url: string) => void;
}

/** A message from the page, when it is one: JSON-RPC 2.0, with a method or an id. */
export function asMessage(data: unknown): JsonRpcMessage | null {
  if (typeof data !== "object" || data === null) return null;
  const message = data as Record<string, unknown>;
  if (message.jsonrpc !== "2.0") return null;
  const params = message.params;
  return {
    jsonrpc: "2.0",
    id: typeof message.id === "string" || typeof message.id === "number" ? message.id : undefined,
    method: typeof message.method === "string" ? message.method : undefined,
    params:
      typeof params === "object" && params !== null ? (params as Record<string, unknown>) : {},
  };
}

/** The `ui/initialize` answer: what this host is and offers. */
function initializeResult(context: HostContext) {
  return {
    protocolVersion: MCP_APPS_PROTOCOL,
    hostInfo: { name: "AgenticOS", version: "1" },
    hostCapabilities: { serverTools: {}, serverResources: {}, openLinks: {} },
    hostContext: hostContext(context),
  };
}

export function hostContext(context: HostContext) {
  return {
    theme: context.theme,
    locale: context.locale,
    displayMode: "inline",
    availableDisplayModes: ["inline"],
    toolInfo: { tool: { name: context.toolName } },
  };
}

/** An `http(s)` address, or null for anything a link should not open (`javascript:`, `data:`). */
export function openableUrl(value: unknown): string | null {
  if (typeof value !== "string") return null;
  try {
    const url = new URL(value);
    return url.protocol === "https:" || url.protocol === "http:" ? url.href : null;
  } catch {
    return null;
  }
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function reply(id: string | number, result: unknown): JsonRpcReply {
  return { jsonrpc: "2.0", id, result };
}

function failure(id: string | number, code: number, message: string): JsonRpcReply {
  return { jsonrpc: "2.0", id, error: { code, message } };
}

/**
 * The answer to one request from the page.
 *
 * What the host does not offer - sending a message as the person, changing what
 * the model is told, another display mode - is answered as not found, which a page
 * written for MCP Apps treats as a host without it.
 */
export async function answer(
  message: JsonRpcMessage & { id: string | number; method: string },
  context: HostContext,
  actions: HostActions,
): Promise<JsonRpcReply> {
  const { id, method, params = {} } = message;
  switch (method) {
    case "ui/initialize":
      return reply(id, initializeResult(context));
    case "ping":
      return reply(id, {});
    case "ui/request-display-mode":
      return reply(id, { mode: "inline" });
    case "ui/open-link": {
      const url = openableUrl(params.url);
      // i18n-exempt: a JSON-RPC error to the page, never shown to a person
      if (url === null) return failure(id, INVALID_PARAMS, "Only http and https links open");
      actions.openLink(url);
      return reply(id, {});
    }
    case "tools/call": {
      const name = params.name;
      const args = params.arguments === undefined ? {} : params.arguments;
      if (typeof name !== "string" || !isObject(args)) {
        // i18n-exempt: a JSON-RPC error to the page, never shown to a person
        return failure(id, INVALID_PARAMS, "A tool call needs a name and an arguments object");
      }
      return relayed(id, () => actions.callTool(name, args));
    }
    case "resources/read": {
      // i18n-exempt: a JSON-RPC error to the page, never shown to a person
      if (typeof params.uri !== "string") return failure(id, INVALID_PARAMS, "A read needs a uri");
      const uri = params.uri;
      return relayed(id, () => actions.readResource(uri));
    }
    default:
      // i18n-exempt: a JSON-RPC error to the page, never shown to a person
      return failure(id, METHOD_NOT_FOUND, `${method} is not supported here`);
  }
}

async function relayed(id: string | number, call: () => Promise<unknown>): Promise<JsonRpcReply> {
  try {
    return reply(id, await call());
  } catch (error) {
    // The backend's refusal says why ("needs a person's approval"); anything else
    // is the network's, and the page needs only to know the call did not happen.
    // i18n-exempt: a JSON-RPC error to the page, never shown to a person
    const text = error instanceof ApiError ? error.message : "The request did not reach the server";
    return failure(id, SERVER_ERROR, text);
  }
}
