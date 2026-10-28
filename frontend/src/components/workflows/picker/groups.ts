import {
  HIDDEN_CATEGORIES,
  PICKER_SECTIONS,
  categoryRank,
  operationRank,
} from "@/components/workflows/node-visuals";
import { type WorkflowApp, WORKFLOW_APPS, appForCatalogKey } from "@/components/workflows/apps";
import { connectionLabel, offeredTools } from "@/lib/mcp-servers";
import type { UsableMcpConnectionRecord } from "@/lib/org-mcp-connections-api";
import type { NodeDefinition } from "@/lib/workflows/types";

/** One tool of an organization MCP connection, offered as a step of its app. */
export interface AppAction {
  /** Unique among the actions: the connection and the tool. */
  key: string;
  app: WorkflowApp;
  connectionId: string;
  connectionName: string;
  /** The tool's own name, as the server lists it. */
  tool: string;
  description: string;
  /** The `mcp.call` definition the action adds, set up for this connection and tool. */
  definition: NodeDefinition;
}

/** What an app's group holds beside its triggers: the connections' tools, or the way to get some. */
export interface PickerApp {
  app: WorkflowApp;
  actions: AppAction[];
  /** A connection with no recorded tools, by name: it needs a test to list them. */
  untested: { id: string; name: string }[];
  /** The catalog entry to open when no connection provides the app's actions, else null. */
  connectKey: string | null;
  /** The member may not edit workflows, so the group cannot say what it holds. */
  needsPermission: boolean;
}

/** Who may add actions: the organization's connections, or null when they are not known here. */
export interface AppSource {
  connections: readonly UsableMcpConnectionRecord[] | null;
  /** Whether the member may connect one, so a group may offer to. */
  canConnect: boolean;
  /** The member may not read connections at all, as opposed to the list still loading. */
  unavailable?: boolean;
}

/** One group of steps - a catalog `category`, such as `slack` or `tables`. */
export interface PickerGroup {
  category: string;
  /** The group's steps; an app's group holds its native triggers here. */
  items: NodeDefinition[];
  /** Set on an app's group, which also holds that app's MCP actions. */
  app?: PickerApp;
}

/** A heading in the picker and the groups under it. */
export interface PickerSection {
  id: string;
  groups: PickerGroup[];
}

/** The section that collects a category no section names. */
export const MORE_SECTION = "more";

/**
 * The offered steps as the picker lists them: sections in the order a workflow
 * reads, each with its groups, each group's steps in catalog order. Empty
 * groups and sections are left out, and a hidden category never shows. A chat
 * platform's steps are listed acting first: send, read, list, find.
 */
export function pickerSections(
  definitions: readonly NodeDefinition[],
  source: AppSource = { connections: null, canConnect: false },
): PickerSection[] {
  const byCategory = new Map<string, NodeDefinition[]>();
  for (const definition of definitions) {
    if (HIDDEN_CATEGORIES.has(definition.category)) continue;
    const items = byCategory.get(definition.category) ?? [];
    items.push(definition);
    byCategory.set(definition.category, items);
  }
  // Stable, so a group with no operation order keeps the catalog's.
  for (const items of byCategory.values()) {
    items.sort((a, b) => operationRank(a.id) - operationRank(b.id));
  }
  const apps = appGroups(definitions, source);
  for (const [category, group] of apps) byCategory.set(category, group.items);
  const named = new Set<string>(PICKER_SECTIONS.flatMap((section) => section.groups));
  const sections: PickerSection[] = PICKER_SECTIONS.map((section) => ({
    id: section.id,
    groups: section.groups.flatMap((category) => {
      const items = byCategory.get(category);
      if (items === undefined) return [];
      const app = apps.get(category)?.app;
      return [app === undefined ? { category, items } : { category, items, app }];
    }),
  }));
  const rest = [...byCategory.keys()]
    .filter((category) => !named.has(category))
    .sort((a, b) => categoryRank(a) - categoryRank(b) || a.localeCompare(b))
    .map((category) => ({ category, items: byCategory.get(category) ?? [] }));
  sections.push({ id: MORE_SECTION, groups: rest });
  return sections.filter((section) => section.groups.length > 0);
}

/**
 * Whether every word of a query occurs, case-insensitively, in any one of the fields:
 * so "gmail read mess" finds a field set naming Gmail and "Read message", in any order.
 * An empty query matches everything.
 */
function matchesWords(query: string, fields: readonly string[]): boolean {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  const haystack = fields.map((field) => field.toLowerCase());
  return words.every((word) => haystack.some((field) => field.includes(word)));
}

/** Whether a step answers a search, by its name, what it does, its group or its id. */
export function matchesSearch(
  definition: NodeDefinition,
  query: string,
  groupLabel: string,
): boolean {
  return matchesWords(query, [definition.name, definition.description, groupLabel, definition.id]);
}

/**
 * The app groups: each app's native triggers among `definitions`, then one action
 * per tool of every enabled organization connection to the app's MCP server, or
 * the way to connect one when there is none. An app with nothing to show is absent.
 */
function appGroups(
  definitions: readonly NodeDefinition[],
  { connections, canConnect, unavailable = false }: AppSource,
): Map<string, PickerGroup & { app: PickerApp }> {
  const call = definitions.find((definition) => definition.id === "mcp.call");
  const groups = new Map<string, PickerGroup & { app: PickerApp }>();
  for (const app of WORKFLOW_APPS) {
    const triggers = definitions.filter((definition) => app.triggers.includes(definition.id));
    const own = (connections ?? []).filter(
      (connection) => connection.is_enabled && appForCatalogKey(connection.catalog_key) === app,
    );
    const actions: AppAction[] = [];
    const untested: { id: string; name: string }[] = [];
    if (call !== undefined) {
      for (const connection of own) {
        const tools = offeredTools(connection) ?? [];
        if (tools.length === 0) {
          untested.push({ id: connection.id, name: connectionLabel(connection) });
        }
        for (const tool of tools) {
          actions.push({
            key: `${connection.id}:${tool.name}`,
            app,
            connectionId: connection.id,
            connectionName: connectionLabel(connection),
            tool: tool.name,
            description: tool.description,
            definition: call,
          });
        }
      }
    }
    const connectKey =
      call !== undefined && canConnect && connections !== null && own.length === 0
        ? app.catalogKeys[0]
        : null;
    // Not known, not none: this member may not read the connections.
    const needsPermission = call !== undefined && unavailable;
    if (
      triggers.length === 0 &&
      actions.length === 0 &&
      untested.length === 0 &&
      connectKey === null &&
      !needsPermission
    ) {
      continue;
    }
    groups.set(app.id, {
      category: app.id,
      items: triggers,
      app: { app, actions, untested, connectKey, needsPermission },
    });
  }
  return groups;
}

/**
 * Whether an app's action answers a search, by the app, what it is called, its tool's
 * name - as written and with its underscores read as spaces - its connection or what it does.
 */
export function matchesAction(
  action: AppAction,
  query: string,
  label: string,
  appName: string,
): boolean {
  return matchesWords(query, [
    appName,
    label,
    action.tool,
    action.tool.replace(/_/g, " "),
    action.connectionName,
    action.description,
  ]);
}
