/**
 * The console's copy on the device (#2097): recent conversations and the
 * approvals queue to read without a network, and the outbox of messages
 * written without one.
 *
 * Kept only where the console is an app - the desktop or phone shell, or a PWA
 * added to the home screen. A browser tab keeps nothing, so a shared computer
 * holds no copy of anybody's conversations. Sealed (`sealed-store.ts`), kept
 * for one account, and deleted with the tenant's state on a switch or a
 * sign-out (`resetTenantState`).
 *
 * A copy is a convenience the server's answer always replaces. Writing one is
 * best effort: a write that fails leaves the previous copy, or none, and is
 * reported where a developer looks; it never fails the request it rode on.
 */

import { CONSOLE_WORKER } from "@/lib/console-worker";
import { getFileUrl } from "@/lib/file-url";
import { readShellInfo } from "@/lib/desktop/shell";
import { useAuthStore } from "@/stores/auth-store";
import { useOfflineStore, type OutboxCount } from "@/stores/offline-store";
import type {
  ConversationListResponse,
  ConversationMessagesResponse,
  OrganizationList,
  QueuedMessage,
} from "@/types";
import type { MyPermissions } from "@/types/permissions";
import type { AgentList } from "@/types/agents";
import type { Conversation } from "@/types/conversation";
import type { AgentRunList, ApprovalList, CostSummary } from "@/types/runs";
import { SealedStore, wipeSealedStore } from "./sealed-store";

/** The conversations kept to read offline: the ones opened most recently. */
export const RECENT_CONVERSATIONS = 20;
/** How long a copy stays readable. The outbox is the person's own words and does not expire. */
export const KEEP_FOR_MS = 7 * 24 * 60 * 60 * 1000;
/** A conversation's files kept to open offline: its newest this many, each up to the size below. */
export const KEPT_FILES_PER_CONVERSATION = 20;
export const MAX_KEPT_FILE_BYTES = 5 * 1024 * 1024;

/** An attachment kept to open offline: its type, and its bytes as base64. */
export interface KeptFile {
  type: string;
  data: string;
}

export interface OfflineRecords {
  /** What the person may do, so the console offline draws what it draws online. */
  permissions: MyPermissions;
  organizations: OrganizationList;
  /**
   * The agents, unfiltered: `agents:all` with the archived (the chat's picker,
   * and the names and faces beside old answers), `agents:active` without.
   */
  "agents:all": AgentList;
  "agents:active": AgentList;
  approvals: ApprovalList;
  /** Conversation ids, most recently opened first. */
  recent: string[];
  [list: `list:${string}`]: ConversationListResponse;
  [messages: `messages:${string}`]: ConversationMessagesResponse;
  /** A conversation's outbox; `outbox:new` is a new chat's, before it has an id. */
  [outbox: `outbox:${string}`]: QueuedMessage[];
  /** The ids of the files kept for a conversation, deleted with it. */
  [attachments: `attachments:${string}`]: string[];
  [file: `file:${string}`]: KeptFile;
  /** The dashboard's cards, by what they asked: the spend over a range, the
   * newest failures, the conversations to pick up again (#2097, item 17). */
  [spend: `spend:${string}`]: CostSummary;
  [failures: `failures:${number}`]: AgentRunList;
  [recent: `recent-conversations:${number}`]: { items: Conversation[] };
}

type RecordName = keyof OfflineRecords & string;

/** Whether this console keeps a copy on the device. */
export function offlineAvailable(): boolean {
  if (typeof window === "undefined") return false;
  if (!("indexedDB" in window) || !window.crypto?.subtle) return false;
  return readShellInfo() !== null || window.matchMedia?.("(display-mode: standalone)").matches;
}

/** A request that never reached the server - what `fetch` rejects with offline. */
export function isNetworkFailure(error: unknown): boolean {
  return error instanceof TypeError;
}

function report(what: string, error: unknown): void {
  console.warn("offline", what, error);
}

/** Bumped by every wipe: a write that set out before one belongs to what was wiped. */
let generation = 0;
let opened: { owner: string; store: Promise<SealedStore<OfflineRecords>> } | null = null;
/** The last wipe; a store opens after it, or it would open the database being deleted. */
let wiping: Promise<void> = Promise.resolve();

function storeFor(owner: string): Promise<SealedStore<OfflineRecords>> {
  if (opened?.owner !== owner) {
    opened?.store.then(
      (store) => store.close(),
      () => undefined,
    );
    opened = { owner, store: wiping.then(() => SealedStore.open<OfflineRecords>(owner)) };
  }
  return opened.store;
}

/**
 * Who a request was made for, taken before it is sent: the copy of its answer
 * is written only if that is still who is signed in and nothing was wiped since.
 * An answer landing after a switch of organization would otherwise be kept in
 * the next one's copy.
 */
interface Ticket {
  owner: string;
  generation: number;
}

function ticket(): Ticket | null {
  if (!offlineAvailable()) return null;
  const owner = useAuthStore.getState().user?.id;
  return owner ? { owner, generation } : null;
}

function current(asked: Ticket): boolean {
  return asked.generation === generation && useAuthStore.getState().user?.id === asked.owner;
}

async function keep<K extends RecordName>(
  asked: Ticket,
  name: K,
  value: OfflineRecords[K],
  then?: (
    store: SealedStore<OfflineRecords>,
    value: OfflineRecords[K],
    stillCurrent: () => boolean,
  ) => Promise<void>,
): Promise<void> {
  try {
    const store = await storeFor(asked.owner);
    if (!current(asked)) return;
    await store.put(name, value);
    await then?.(store, value, () => current(asked));
  } catch (error) {
    // i18n-exempt: a developer's log label, never shown
    report(`keep ${name}`, error);
  }
}

/**
 * The server's answer, kept on the device; or, when the server cannot be
 * reached, the copy kept last time - and the offline banner told the screen is
 * a copy. With no copy, or any failure but the network's, the failure stands.
 */
export async function readThrough<K extends RecordName>(
  name: K,
  fetch: () => Promise<OfflineRecords[K]>,
  then?: (
    store: SealedStore<OfflineRecords>,
    value: OfflineRecords[K],
    stillCurrent: () => boolean,
  ) => Promise<void>,
): Promise<OfflineRecords[K]> {
  const asked = ticket();
  try {
    const value = await fetch();
    if (asked) {
      void keep(asked, name, value, then);
      // The server answers again: the screen is on its way back to its answers.
      useOfflineStore.getState().backOnline();
    }
    return value;
  } catch (error) {
    if (!asked || !isNetworkFailure(error)) throw error;
    let kept;
    try {
      kept = await (await storeFor(asked.owner)).get(name, KEEP_FOR_MS);
    } catch (readError) {
      // i18n-exempt: a developer's log label, never shown
      report(`read ${name}`, readError);
      throw error;
    }
    if (!kept || !current(asked)) throw error;
    useOfflineStore.getState().servedFromDevice(kept.savedAt);
    return kept.value;
  }
}

/** One conversation's messages, read through - and the conversation moved to the front of the recent ones. */
export function readConversation(
  id: string,
  fetch: () => Promise<ConversationMessagesResponse>,
): Promise<ConversationMessagesResponse> {
  return readThrough(`messages:${id}`, fetch, async (store, thread, stillCurrent) => {
    const recent = (await store.get("recent"))?.value ?? [];
    const next = [id, ...recent.filter((kept) => kept !== id)];
    for (const dropped of next.slice(RECENT_CONVERSATIONS)) {
      await store.delete(`messages:${dropped}`);
      for (const file of (await store.get(`attachments:${dropped}`))?.value ?? []) {
        await store.delete(`file:${file}`);
      }
      await store.delete(`attachments:${dropped}`);
    }
    await store.put("recent", next.slice(0, RECENT_CONVERSATIONS));
    await keepAttachments(store, id, thread, stillCurrent);
  });
}

async function base64(blob: Blob): Promise<string> {
  const bytes = new Uint8Array(await blob.arrayBuffer());
  let binary = "";
  // In slices: spreading megabytes into one call overflows the stack.
  for (let i = 0; i < bytes.length; i += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  }
  return btoa(binary);
}

/**
 * The thread's newest files, so they open offline too (#2097) - fetched the
 * first time the thread is read with them and never again. One that is too
 * large or will not load is left to the network.
 */
async function keepAttachments(
  store: SealedStore<OfflineRecords>,
  conversationId: string,
  thread: ConversationMessagesResponse,
  stillCurrent: () => boolean,
): Promise<void> {
  const wanted = [
    ...new Set(thread.items.flatMap((message) => (message.files ?? []).map((file) => file.id))),
  ].slice(-KEPT_FILES_PER_CONVERSATION);
  const kept = new Set((await store.get(`attachments:${conversationId}`))?.value ?? []);
  for (const id of wanted) {
    if (kept.has(id)) continue;
    const response = await globalThis.fetch(getFileUrl(id), { credentials: "include" });
    if (!response.ok) continue;
    const blob = await response.blob();
    if (blob.size > MAX_KEPT_FILE_BYTES) continue;
    // A fetch takes a while; the tenant may have been left in the meantime.
    if (!stillCurrent()) return;
    await store.put(`file:${id}`, { type: blob.type, data: await base64(blob) });
    kept.add(id);
    await store.put(`attachments:${conversationId}`, [...kept]);
  }
}

/** A recent conversation's file, as kept on the device; null when it was not. */
export async function keptFile(id: string): Promise<Blob | null> {
  const asked = ticket();
  if (!asked) return null;
  try {
    const kept = await (await storeFor(asked.owner)).get(`file:${id}`, KEEP_FOR_MS);
    if (!kept || !current(asked)) return null;
    const bytes = Uint8Array.from(atob(kept.value.data), (char) => char.charCodeAt(0));
    return new Blob([bytes], { type: kept.value.type });
  } catch (error) {
    report("read file", error);
    return null;
  }
}

const outboxName = (conversationId: string | null) => `outbox:${conversationId ?? "new"}` as const;

/** What waits in every outbox, for the banner. */
async function countOutboxes(store: SealedStore<OfflineRecords>): Promise<OutboxCount[]> {
  const counts: OutboxCount[] = [];
  for (const name of await store.names("outbox:")) {
    const id = name.slice("outbox:".length);
    const kept = await store.get(`outbox:${id}`);
    // An emptied outbox is deleted, never kept empty.
    if (kept) {
      counts.push({ conversationId: id === "new" ? null : id, count: kept.value.length });
    }
  }
  return counts;
}

/** The messages a conversation's outbox holds, oldest first. */
export async function keptOutbox(conversationId: string | null): Promise<QueuedMessage[]> {
  const asked = ticket();
  if (!asked) return [];
  try {
    const store = await storeFor(asked.owner);
    const kept = await store.get(outboxName(conversationId));
    return current(asked) ? (kept?.value ?? []) : [];
  } catch (error) {
    report("read outbox", error);
    return [];
  }
}

/** Keep a conversation's outbox as it now stands - emptied, it is removed. */
export async function keepOutbox(
  conversationId: string | null,
  messages: readonly QueuedMessage[],
): Promise<void> {
  const asked = ticket();
  if (!asked) return;
  try {
    const store = await storeFor(asked.owner);
    if (!current(asked)) return;
    if (messages.length > 0) await store.put(outboxName(conversationId), [...messages]);
    else await store.delete(outboxName(conversationId));
    useOfflineStore.getState().setOutbox(await countOutboxes(store));
  } catch (error) {
    report("keep outbox", error);
  }
}

/** Read what every outbox holds into the banner - once the account is known. */
export async function refreshOutboxCounts(): Promise<void> {
  const asked = ticket();
  if (!asked) return;
  try {
    const counts = await countOutboxes(await storeFor(asked.owner));
    if (current(asked)) useOfflineStore.getState().setOutbox(counts);
  } catch (error) {
    report("count outbox", error);
  }
}

/**
 * Install the service worker that keeps the console's code, so the app opens
 * without a network (`public/sw.js`). Where WebKit runs it - not in the iOS and
 * macOS apps' web views, which allow service workers only to domains named at
 * build time - a start without a network shows the system's error page instead,
 * and the copy is read from the moment the console is open.
 */
export async function keepConsoleCode(): Promise<void> {
  if (!offlineAvailable() || !("serviceWorker" in navigator)) return;
  try {
    await navigator.serviceWorker.register(CONSOLE_WORKER);
  } catch (error) {
    report("register worker", error);
  }
}

/**
 * Delete the copy - key, conversations, outbox and all. A tenant's state is
 * being dropped, and this is the part of it on the disk.
 */
export function wipeDeviceCache(): void {
  generation += 1;
  useOfflineStore.getState().reset();
  const was = opened;
  opened = null;
  if (!offlineAvailable()) return;
  wiping = (async () => {
    try {
      if (was) (await was.store).close();
    } catch {
      // A store that never opened has nothing to close; the wipe still runs.
    }
    try {
      await wipeSealedStore();
    } catch (error) {
      report("wipe", error);
    }
  })();
}
