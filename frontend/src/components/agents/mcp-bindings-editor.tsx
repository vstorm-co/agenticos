"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { ConnectServerDialog } from "@/components/agents/connect-server-dialog";
import { bindingKey, McpServerPicker } from "@/components/agents/mcp-server-picker";
import type { ToolPickerState } from "@/components/mcp/mcp-server-list-types";
import { McpToolPickerDialog } from "@/components/mcp/mcp-tool-picker-dialog";
import { useMcpCatalog, useOrgMcpConnections, usePermissions } from "@/hooks";
import { getErrorMessage } from "@/lib/api-error";
import { toolsForBinding } from "@/lib/binding-tools";
import { narrowedSelection } from "@/lib/mcp-servers";
import type { OrgMcpConnectionRecord } from "@/lib/org-mcp-connections-api";
import type { McpServerRef } from "@/types/agents";
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
  value,
  onChange,
  disabled,
}: {
  value: McpServerRef[];
  onChange: (next: McpServerRef[]) => void;
  disabled?: boolean;
}) {
  const tErrors = useTranslations("errors");
  const { can } = usePermissions();
  // The organization's servers, never the author's own: a personal connection
  // is refused at publish, so offering one would be offering a choice that
  // cannot be published. `useMcpCatalog` only supplies the names and logos -
  // the ids the spec stores belong to the connections.
  const { connections, test: probe } = useOrgMcpConnections();
  const { servers: catalog } = useMcpCatalog();
  const [connectingServer, setConnectingServer] = useState<McpCatalogEntry | null>(null);
  const [toolPicker, setToolPicker] = useState<ToolPickerState | null>(null);
  // Which binding the open tool picker narrows, by `bindingKey`. Kept beside the
  // picker state rather than inside it because the dialog is shared with the
  // servers page, where a binding is not a thing.
  const [toolBinding, setToolBinding] = useState<string | null>(null);

  return (
    <>
      <McpServerPicker
        connections={connections}
        catalog={catalog}
        value={value}
        onChange={onChange}
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
        onConnect={setConnectingServer}
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
          onChange(
            value.map((ref) =>
              bindingKey(ref) === toolBinding ? { ...ref, allowed_tools: allowed } : ref,
            ),
          );
          setToolPicker(null);
          setToolBinding(null);
        }}
      />

      <ConnectServerDialog
        entry={connectingServer}
        onClose={() => setConnectingServer(null)}
        // Bound as soon as it exists: somebody who connected a server from
        // here was going to tick it next.
        onConnected={(connectionId) =>
          onChange([
            ...value,
            { account: "organization", connection_id: connectionId, allowed_tools: null },
          ])
        }
      />
    </>
  );
}
