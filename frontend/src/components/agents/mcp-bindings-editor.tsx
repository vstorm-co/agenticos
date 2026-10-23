"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import {
  ConnectOwnServerDialog,
  ConnectServerDialog,
  useConnectEntry,
  useSignInOwn,
} from "@/components/agents/connect-server-dialog";
import { bindingKey, McpServerPicker } from "@/components/agents/mcp-server-picker";
import { McpToolLoadNotice } from "@/components/agents/mcp-tool-load-notice";
import type { ToolPickerState } from "@/components/mcp/mcp-server-list-types";
import { McpToolPickerDialog } from "@/components/mcp/mcp-tool-picker-dialog";
import { useMcpCatalog, useMcpConnections, useOrgMcpConnections, usePermissions } from "@/hooks";
import { withCapability } from "@/lib/agent-spec";
import { getErrorMessage } from "@/lib/api-error";
import { toolsForBinding } from "@/lib/binding-tools";
import { hereForMcpOAuthReturn } from "@/lib/mcp-oauth";
import { narrowedSelection } from "@/lib/mcp-servers";
import type { OrgMcpConnectionRecord } from "@/lib/org-mcp-connections-api";
import type { AgentSpec, McpServerRef } from "@/types/agents";
import type { McpCatalogEntry } from "@/types/mcp";
import { Perm } from "@/types/permissions";

/**
 * What the tool picker opens with for one binding.
 *
 * The tools come from the connection's **last successful probe** rather than a
 * fresh one: probing dials out to a third party and is gated on
 * `connections:manage`, which an agent author need not hold (#1341).
 *
 * A connection nothing has probed yet has no catalogue, and a binding that
 * already names tools would then read "0 of 0 on" while its card says three -
 * so the names it holds stand in. They came from the server once, they are what
 * the agent is bound to, and they can at least be narrowed further without a
 * probe. The dialog says where to get the real list.
 */
export function toolChoice(
  ref: McpServerRef,
  connection: OrgMcpConnectionRecord,
  name: string,
): ToolPickerState {
  const probed = connection.last_tools;
  const tools =
    probed ?? (ref.allowed_tools ?? []).map((tool) => ({ name: tool, description: "" }));
  return {
    scope: "organization",
    // The server's name, not the connection's: a binding to each person's own
    // account borrows an organization connection's probe for the catalogue of
    // tools and is not a narrowing of that connection.
    name,
    connection,
    tools,
    checked: new Set(ref.allowed_tools ?? tools.map((one) => one.name)),
    appliesTo: "agent",
  };
}

/**
 * The MCP servers an agent spec binds, edited in full: which servers, which of
 * their tools, and a server connected on the spot.
 *
 * One editor for every place a spec is written - the Builder, and a workflow
 * step that configures its agent in place - so narrowing a server's tools or
 * connecting a new one works the same in both.
 */
export function McpBindingsEditor({
  spec,
  onChange,
  disabled,
}: {
  spec: AgentSpec;
  onChange: (changes: Partial<AgentSpec>) => void;
  disabled?: boolean;
}) {
  const value = spec.mcp_servers;
  const setServers = (mcp_servers: McpServerRef[]) => onChange({ mcp_servers });
  const tErrors = useTranslations("errors");
  const { can } = usePermissions();
  // A binding to the organization's connection names its id; one to each
  // person's own account names the catalog entry, so the author's own
  // connections are listed to read tool counts and to connect or sign in.
  // `useMcpCatalog` only supplies the names and logos.
  const { connections, test: probe } = useOrgMcpConnections();
  const { connections: myConnections } = useMcpConnections();
  const { servers: catalog } = useMcpCatalog();
  const [connectingServer, setConnectingServer] = useState<McpCatalogEntry | null>(null);
  const [connectingOwnServer, setConnectingOwnServer] = useState<McpCatalogEntry | null>(null);
  const connectServer = useConnectEntry("organization", {
    openForm: setConnectingServer,
    held: connections,
  });
  const signInOwn = useSignInOwn({ returnTo: hereForMcpOAuthReturn() });
  const connectOwn = useConnectEntry("personal", {
    returnTo: hereForMcpOAuthReturn(),
    openForm: setConnectingOwnServer,
    held: myConnections,
  });
  const [toolPicker, setToolPicker] = useState<ToolPickerState | null>(null);
  // Which binding the open tool picker narrows, by `bindingKey`. Kept beside the
  // picker state rather than inside it because the dialog is shared with the
  // servers page, where a binding is not a thing.
  const [toolBinding, setToolBinding] = useState<string | null>(null);

  return (
    <>
      <McpToolLoadNotice
        className="mb-4"
        spec={spec}
        connections={connections}
        personalConnections={myConnections}
        onEnableToolSearch={() =>
          onChange({ capabilities: withCapability(spec.capabilities, "tool_search", true) })
        }
        disabled={disabled}
      />
      <McpServerPicker
        connections={connections}
        catalog={catalog}
        value={value}
        onChange={setServers}
        personalConnections={myConnections}
        onConnectOwn={connectOwn}
        onSignInOwn={signInOwn}
        onTools={async (ref, connection, name) => {
          setToolBinding(bindingKey(ref));
          // A connection nobody has checked has no tool list; check it here for
          // whoever may, rather than sending them to the servers page to press
          // the button and find their way back.
          try {
            const { connection: probed, error } = await toolsForBinding(
              connection,
              can(Perm.connectionsManage) ? probe : null,
            );
            if (error !== null) toast.error(error);
            setToolPicker(toolChoice(ref, probed, name));
          } catch (caught) {
            toast.error(getErrorMessage(caught, tErrors));
            setToolPicker(toolChoice(ref, connection, name));
          }
        }}
        onConnect={connectServer}
        disabled={disabled}
      />

      <McpToolPickerDialog
        toolPicker={toolPicker}
        setToolPicker={setToolPicker}
        submitting={false}
        // Written into the spec rather than onto the connection: this is the
        // agent's narrowing, and the connection's own allowlist is everybody's.
        // Every tool checked means "no narrowing from here", which is null - not
        // a list that would freeze out a tool the server adds later.
        onSave={() => {
          if (toolPicker === null) return;
          const allowed = narrowedSelection(
            toolPicker.checked,
            toolPicker.tools,
            // Only a real probe can mean "everything": where the catalogue is
            // the binding's own names, all-checked is true by construction.
            toolPicker.connection.last_tools !== null,
          );
          setServers(
            value.map((ref) =>
              bindingKey(ref) === toolBinding ? { ...ref, allowed_tools: allowed } : ref,
            ),
          );
          setToolPicker(null);
          setToolBinding(null);
        }}
      />

      <ConnectOwnServerDialog
        entry={connectingOwnServer}
        onClose={() => setConnectingOwnServer(null)}
        returnTo={hereForMcpOAuthReturn()}
      />

      <ConnectServerDialog
        entry={connectingServer}
        onClose={() => setConnectingServer(null)}
        // Bound as soon as it exists: somebody who connected a server from
        // here was going to tick it next, and its tools come up at once from
        // the check that connecting just ran (#2073).
        onConnected={(connection) => {
          const bound: McpServerRef = {
            account: "organization",
            connection_id: connection.id,
            allowed_tools: null,
            approval: "none",
          };
          setServers([...value, bound]);
          setToolBinding(bindingKey(bound));
          setToolPicker(toolChoice(bound, connection, connection.label ?? connection.name));
        }}
      />
    </>
  );
}
