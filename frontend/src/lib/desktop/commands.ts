/**
 * The shell's commands, typed, and what they answer, checked.
 *
 * Each function is one command from `console.rs`. What comes back crosses a
 * process boundary from a binary that may be older or newer than this page, so
 * it is decoded here rather than cast: a shape this console does not know is a
 * `ShellError`, not a settings page drawn from `undefined`.
 */

import { isLook, type Look } from "@/lib/appearance";
import { invokeShell, ShellError } from "@/lib/desktop/shell";
import type { Theme } from "@/stores/theme-store";

export interface Appearance {
  look: Look;
  mode: Theme;
}

export type BlobbyCharacter =
  | { kind: "cast"; id: string }
  | { kind: "agent"; agent_id: string; slug: string; name: string; color_slot: number | null }
  | { kind: "custom"; seed: string; color_slot: number | null };

export const CHATTER = ["quiet", "normal", "chatty"] as const;
export type Chatter = (typeof CHATTER)[number];

/** How small and how large blobby may be made - the shell holds it to the same range. */
export const BLOBBY_SIZE = { min: 0.6, max: 1.6 } as const;

export interface BlobbySettings {
  enabled: boolean;
  character: BlobbyCharacter;
  chatter: Chatter;
  /** Bubbles about runs, approvals and questions. */
  activity: boolean;
  /** Strolls along the bottom of the screen when idle. */
  roams: boolean;
  /** How big it is, as a multiple of its natural size (`BLOBBY_SIZE`). */
  size: number;
  position: { x: number; y: number } | null;
}

export const SHORTCUT_ACTIONS = ["quick_ask", "screenshot_chat", "dictate", "voice_call"] as const;
export type ShortcutAction = (typeof SHORTCUT_ACTIONS)[number];

export interface ShortcutBinding {
  action: ShortcutAction;
  accelerator: string | null;
  /** Set when the binding could not be taken, because another application holds it. */
  problem: string | null;
}

export interface WindowPreferences {
  keep_running: boolean;
  badge: boolean;
  launch_at_login: boolean;
}

/** An agent in the tray's and the Dock's "New Chat With" (`pinned.rs`). */
export interface PinnedAgent {
  id: string;
  name: string;
}

export interface DesktopState {
  appearance: Appearance;
  blobby: BlobbySettings;
  pinned: PinnedAgent[];
  shortcuts: ShortcutBinding[];
  window: WindowPreferences;
}

export type Notice =
  | { kind: "inbox"; title: string; body: string; path: string }
  | {
      kind: "approval";
      title: string;
      body: string;
      path: string;
      approval_id: string;
      approve_label: string;
      reject_label: string;
    };

export interface ApprovalDecision {
  approval_id: string;
  approved: boolean;
}

type Fields = Record<string, unknown>;

function record(value: unknown, what: string): Fields {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new ShellError("malformed", what);
  }
  return value as Fields;
}

function field<T>(fields: Fields, key: string, guard: (value: unknown) => value is T): T {
  const value = fields[key];
  if (!guard(value)) throw new ShellError("malformed", key);
  return value;
}

const isString = (value: unknown): value is string => typeof value === "string";
const isBoolean = (value: unknown): value is boolean => typeof value === "boolean";
const isNumber = (value: unknown): value is number =>
  typeof value === "number" && Number.isFinite(value);
const isSlot = (value: unknown): value is number | null => value === null || isNumber(value);
const isMode = (value: unknown): value is Theme =>
  value === "light" || value === "dark" || value === "system";
const isChatter = (value: unknown): value is Chatter =>
  (CHATTER as readonly unknown[]).includes(value);
const isAction = (value: unknown): value is ShortcutAction =>
  (SHORTCUT_ACTIONS as readonly unknown[]).includes(value);
const isNullableString = (value: unknown): value is string | null =>
  value === null || isString(value);

function parseCharacter(value: unknown): BlobbyCharacter {
  const fields = record(value, "a character");
  switch (fields.kind) {
    case "cast":
      return { kind: "cast", id: field(fields, "id", isString) };
    case "agent":
      return {
        kind: "agent",
        agent_id: field(fields, "agent_id", isString),
        slug: field(fields, "slug", isString),
        name: field(fields, "name", isString),
        color_slot: field(fields, "color_slot", isSlot),
      };
    case "custom":
      return {
        kind: "custom",
        seed: field(fields, "seed", isString),
        color_slot: field(fields, "color_slot", isSlot),
      };
    default:
      throw new ShellError("malformed", "character");
  }
}

function parsePosition(value: unknown): BlobbySettings["position"] {
  if (value === null) return null;
  const fields = record(value, "a position");
  return { x: field(fields, "x", isNumber), y: field(fields, "y", isNumber) };
}

export function parseBlobbySettings(value: unknown): BlobbySettings {
  const fields = record(value, "blobby's settings");
  return {
    enabled: field(fields, "enabled", isBoolean),
    character: parseCharacter(fields.character),
    chatter: field(fields, "chatter", isChatter),
    activity: field(fields, "activity", isBoolean),
    roams: field(fields, "roams", isBoolean),
    // A shell from before blobby could be resized sends none: its natural size.
    size: fields.size === undefined ? 1 : field(fields, "size", isNumber),
    position: parsePosition(fields.position ?? null),
  };
}

function parseBinding(value: unknown): ShortcutBinding {
  const fields = record(value, "a shortcut");
  return {
    action: field(fields, "action", isAction),
    accelerator: field(fields, "accelerator", isNullableString),
    problem: field(fields, "problem", isNullableString),
  };
}

/** The shell's pinned agents; none from a shell older than pinning. */
function parsePinned(value: unknown): PinnedAgent[] {
  if (value === undefined) return [];
  if (!Array.isArray(value)) throw new ShellError("malformed", "the pinned agents");
  return value.map((item: unknown) => {
    const agent = record(item, "a pinned agent");
    return { id: field(agent, "id", isString), name: field(agent, "name", isString) };
  });
}

export function parseDesktopState(value: unknown): DesktopState {
  const fields = record(value, "its state");
  const appearance = record(fields.appearance, "an appearance");
  const window = record(fields.window, "window preferences");
  if (!Array.isArray(fields.shortcuts)) throw new ShellError("malformed", "shortcuts");
  return {
    appearance: {
      look: field(appearance, "look", isLook),
      mode: field(appearance, "mode", isMode),
    },
    blobby: parseBlobbySettings(fields.blobby),
    pinned: parsePinned(fields.pinned),
    // An action this console does not know - a newer shell's - is left out
    // rather than failing the whole page.
    shortcuts: fields.shortcuts
      .filter((binding: unknown) => isAction(record(binding, "a shortcut").action))
      .map(parseBinding),
    window: {
      keep_running: field(window, "keep_running", isBoolean),
      badge: field(window, "badge", isBoolean),
      launch_at_login: field(window, "launch_at_login", isBoolean),
    },
  };
}

export function parseApprovalDecision(value: unknown): ApprovalDecision {
  const fields = record(value, "a decision");
  return {
    approval_id: field(fields, "approval_id", isString),
    approved: field(fields, "approved", isBoolean),
  };
}

export async function getDesktopState(): Promise<DesktopState> {
  return parseDesktopState(await invokeShell("desktop_state"));
}

export async function setAppearance(appearance: Appearance): Promise<void> {
  await invokeShell("set_appearance", { appearance });
}

export async function setBlobby(blobby: BlobbySettings): Promise<void> {
  await invokeShell("set_blobby", { blobby });
}

/** Rebind a shortcut, or switch it off with `null`. Resolves to what is now bound. */
export async function setShortcut(
  action: ShortcutAction,
  accelerator: string | null,
): Promise<string | null> {
  const bound = await invokeShell("set_shortcut", { action, accelerator });
  if (!isNullableString(bound)) throw new ShellError("malformed", "binding");
  return bound;
}

export async function setWindowPreferences(preferences: WindowPreferences): Promise<void> {
  await invokeShell("set_window_preferences", { preferences });
}

export async function notify(notice: Notice): Promise<void> {
  await invokeShell("notify", { notice });
}

export async function setBadge(count: number): Promise<void> {
  await invokeShell("set_badge", { count: Math.max(0, Math.floor(count)) });
}

/** Pin an agent to "New Chat With", or rename it there. Resolves to the list as it now stands. */
export async function pinAgent(agent: PinnedAgent): Promise<PinnedAgent[]> {
  return parsePinned(await invokeShell("pin_agent", { agent }));
}

export async function unpinAgent(id: string): Promise<PinnedAgent[]> {
  return parsePinned(await invokeShell("unpin_agent", { id }));
}

export async function openInConsole(path: string): Promise<void> {
  await invokeShell("open_in_console", { path });
}

export async function openChat(): Promise<void> {
  await invokeShell("open_chat");
}

export async function showConsole(): Promise<void> {
  await invokeShell("show_console");
}

/** Open the shell's own server picker; only its local form may choose an address. */
export async function changeServer(): Promise<void> {
  await invokeShell("change_server");
}

export async function saveBlobbyPosition(x: number, y: number): Promise<void> {
  await invokeShell("save_blobby_position", { x, y });
}

export async function resizeBlobby(size: number): Promise<void> {
  await invokeShell("resize_blobby", {
    size: Math.min(BLOBBY_SIZE.max, Math.max(BLOBBY_SIZE.min, size)),
  });
}

export async function showBlobbyMenu(): Promise<void> {
  await invokeShell("blobby_menu");
}

export async function resizeQuickAsk(height: number): Promise<void> {
  await invokeShell("resize_quick_ask", { height });
}

/** The desktop welcome is through; from now on the app opens on the console itself. */
export async function finishOnboarding(): Promise<void> {
  await invokeShell("finish_onboarding");
}

export async function hideQuickAsk(): Promise<void> {
  await invokeShell("hide_quick_ask");
}

/** This computer's own connection to the server, as the shell reports it (#2305). */
export interface DeviceStatus {
  /** The app holds a session of its own for this server. */
  linked: boolean;
  /** Its socket is open right now: the person's runs can reach this computer. */
  connected: boolean;
}

/** What the shell emits whenever the connection opens, drops or is unlinked. */
export const DEVICE_STATUS_EVENT = "device-status";

export function parseDeviceStatus(value: unknown): DeviceStatus {
  const fields = record(value, "a device status");
  return {
    linked: field(fields, "linked", isBoolean),
    connected: field(fields, "connected", isBoolean),
  };
}

export async function getDeviceStatus(): Promise<DeviceStatus> {
  return parseDeviceStatus(await invokeShell("device_status"));
}

/** Link this computer with a pairing code; the shell asks the person to confirm. */
export async function linkDevice(code: string): Promise<DeviceStatus> {
  return parseDeviceStatus(await invokeShell("device_link", { code }));
}

export async function unlinkDevice(): Promise<DeviceStatus> {
  return parseDeviceStatus(await invokeShell("device_unlink"));
}

/** How far a run may reach in a folder on this computer, server-side names. */
export type LocalMode = "read_only" | "workspace_write" | "full_access";

const LOCAL_MODES: readonly LocalMode[] = ["read_only", "workspace_write", "full_access"];
const isLocalMode = (value: unknown): value is LocalMode =>
  LOCAL_MODES.some((mode) => mode === value);

/** Where a run works on the person's own computer: a granted folder and a mode within it. */
export interface LocalTarget {
  folder: string;
  mode: LocalMode;
  browser?: boolean;
  model_service?: string | null;
  mcp_services?: string[];
}

/** A folder the person allowed their agents to work in, and the most they may do there. */
export interface LocalGrant {
  path: string;
  mode: LocalMode;
}

/** The granted folders, and the modes this computer's sandbox can offer for a new one. */
export interface LocalState {
  grants: LocalGrant[];
  modes: LocalMode[];
}

function parseLocalGrant(value: unknown): LocalGrant {
  const fields = record(value, "a folder grant");
  return { path: field(fields, "path", isString), mode: field(fields, "mode", isLocalMode) };
}

export function parseLocalState(value: unknown): LocalState {
  const fields = record(value, "the granted folders");
  if (!Array.isArray(fields.grants) || !Array.isArray(fields.modes))
    throw new ShellError("malformed", "the granted folders");
  const grants = fields.grants;
  const modes = fields.modes;
  return { grants: grants.map(parseLocalGrant), modes: modes.filter(isLocalMode) };
}

export async function getLocalState(): Promise<LocalState> {
  return parseLocalState(await invokeShell("local_grants"));
}

/** The native folder picker; null when the person closed it without choosing. */
export async function pickLocalFolder(mode: LocalMode): Promise<LocalGrant | null> {
  const picked = await invokeShell("local_pick_folder", { mode });
  return picked === null ? null : parseLocalGrant(picked);
}

export async function revokeLocalFolder(path: string): Promise<LocalState> {
  return parseLocalState(await invokeShell("local_revoke", { path }));
}

/** A file or folder in a granted folder, as the app lists it for the chat's file panel. */
export interface LocalFile {
  path: string;
  size: number | null;
  is_dir: boolean;
  /** Seconds since the epoch. */
  modified: number | null;
}

const isNumberOrNull = (value: unknown): value is number | null =>
  value === null || typeof value === "number";

function parseLocalFile(value: unknown): LocalFile {
  const fields = record(value, "a local file");
  return {
    path: field(fields, "path", isString),
    size: field(fields, "size", isNumberOrNull),
    is_dir: field(fields, "is_dir", isBoolean),
    modified: field(fields, "modified", isNumberOrNull),
  };
}

/** What is in a folder the person granted, newest first; refused for any other. */
export async function listLocalFiles(root: string): Promise<LocalFile[]> {
  const answer = await invokeShell("local_files", { root });
  if (!Array.isArray(answer)) throw new ShellError("malformed", "a folder's files");
  return answer.map(parseLocalFile);
}

/** One file in a granted folder, as bytes. */
export async function readLocalFile(root: string, path: string): Promise<Uint8Array<ArrayBuffer>> {
  const answer = await invokeShell("local_file", { root, path });
  if (typeof answer !== "string") throw new ShellError("malformed", "a file");
  return Uint8Array.from(atob(answer), (char) => char.charCodeAt(0));
}

export interface LocalService {
  id: string;
  name: string;
  kind: "model" | "mcp";
  endpoint: string;
  model: string | null;
}

function parseLocalService(value: unknown): LocalService {
  const fields = record(value, "a local service");
  const kind = fields.kind;
  if (kind !== "model" && kind !== "mcp") throw new ShellError("malformed", "a service kind");
  return {
    id: field(fields, "id", isString),
    name: field(fields, "name", isString),
    kind,
    endpoint: field(fields, "endpoint", isString),
    model: field(
      fields,
      "model",
      (value): value is string | null => value === null || isString(value),
    ),
  };
}

function parseLocalServices(value: unknown): LocalService[] {
  if (!Array.isArray(value)) throw new ShellError("malformed", "local services");
  return value.map(parseLocalService);
}

export async function getLocalServices(): Promise<LocalService[]> {
  return parseLocalServices(await invokeShell("local_services"));
}

export async function saveLocalService(service: LocalService): Promise<LocalService[]> {
  return parseLocalServices(await invokeShell("local_save_service", { service }));
}

export async function removeLocalService(id: string): Promise<LocalService[]> {
  return parseLocalServices(await invokeShell("local_remove_service", { id }));
}
