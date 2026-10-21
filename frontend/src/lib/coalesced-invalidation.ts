import type { QueryClient, QueryKey } from "@tanstack/react-query";

/**
 * How long invalidations are gathered before they are sent.
 *
 * One chat turn marked the sidebar stale five times in a second - the turn's
 * own frames and the live feed's echo of the same change - and each one refetched
 * every page the list held: ten `GET /conversations` for one reply.
 */
export const COALESCE_MS = 250;

interface Batch {
  keys: Map<string, QueryKey>;
  timer: ReturnType<typeof setTimeout>;
  done: Promise<void>;
  resolve: () => void;
  reject: (error: unknown) => void;
}

const batches = new WeakMap<QueryClient, Batch>();

function covers(prefix: QueryKey, key: QueryKey): boolean {
  return prefix.length <= key.length && prefix.every((part, i) => part === key[i]);
}

/**
 * Mark `queryKey` stale with whatever else is marked in the next `COALESCE_MS`,
 * once each. A key a shorter one already covers is not sent twice.
 *
 * Resolves when the batch it joined has been refetched, so a caller that awaited
 * `invalidateQueries` still reads fresh data afterwards - and rejects with the
 * refetch's error, as `invalidateQueries` itself would have.
 */
export function invalidateSoon(client: QueryClient, queryKey: QueryKey): Promise<void> {
  let batch = batches.get(client);
  if (batch === undefined) {
    let resolve!: () => void;
    let reject!: (error: unknown) => void;
    const done = new Promise<void>((settle, fail) => {
      resolve = settle;
      reject = fail;
    });
    const fresh: Batch = {
      keys: new Map(),
      done,
      resolve,
      reject,
      timer: setTimeout(() => void flush(client, fresh), COALESCE_MS),
    };
    batches.set(client, fresh);
    batch = fresh;
  }
  batch.keys.set(JSON.stringify(queryKey), queryKey);
  return batch.done;
}

async function flush(client: QueryClient, batch: Batch): Promise<void> {
  batches.delete(client);
  const keys = [...batch.keys.values()].sort((a, b) => a.length - b.length);
  const sent: QueryKey[] = [];
  for (const key of keys) {
    if (!sent.some((prefix) => covers(prefix, key))) sent.push(key);
  }
  try {
    await Promise.all(sent.map((queryKey) => client.invalidateQueries({ queryKey })));
  } catch (error) {
    batch.reject(error);
    return;
  }
  batch.resolve();
}
