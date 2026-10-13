import type { McpConnectionTestResult } from "@/lib/mcp-connections-api";
import type { OrgMcpConnectionRecord } from "@/lib/org-mcp-connections-api";

/** What the Builder opens the tool picker with, and what went wrong if anything. */
export interface BindingTools {
  connection: OrgMcpConnectionRecord;
  /** The probe's own refusal, where one was made and failed. Null otherwise. */
  error: string | null;
}

/**
 * The connection a binding's tool picker reads its catalogue from, probed if it
 * has never been.
 *
 * The picker lists a server's tools from the connection's **last successful
 * probe**, and a connection nobody has checked has none - which used to send
 * somebody to the servers page to press *Check* and come back. Probing dials
 * out to a third party and is gated on `connections:manage`, so `probe` is
 * `null` for a caller who may not: they get the empty catalogue and the dialog's
 * sentence about where to get one, exactly as before. A probe that fails leaves
 * the connection as it was and hands back the reason, so the caller can say it
 * rather than open a picker that is quietly empty.
 */
export async function toolsForBinding(
  connection: OrgMcpConnectionRecord,
  probe: ((connectionId: string) => Promise<McpConnectionTestResult>) | null,
): Promise<BindingTools> {
  if (connection.last_tools !== null || probe === null) return { connection, error: null };
  const result = await probe(connection.id);
  if (!result.ok) return { connection, error: result.error };
  return { connection: { ...connection, last_tools: result.tools }, error: null };
}
