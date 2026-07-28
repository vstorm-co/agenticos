"use client";

import { useEffect, useRef } from "react";

/**
 * Refresh a document list while the worker is still ingesting into it.
 *
 * Ingestion is asynchronous: the request that uploads a file returns before the
 * document has been parsed, embedded and stored, so the status the page is
 * holding is stale the moment it arrives. This polls until nothing is pending
 * and then stops entirely — a page with a settled list makes no requests at all.
 *
 * The `/rag` page used to learn this from a server-sent event stream instead.
 * That stream had no authentication and no organization on its events, and it
 * answered 500 in production because its own dependency was constructed wrong;
 * it was deleted rather than rebuilt. Polling asks the same org-scoped endpoint
 * the rest of the page already uses, which is the whole reason it needs no
 * separate authentication story.
 *
 * The backoff exists because a large PDF can take minutes: a fixed 2s interval
 * would be several hundred requests for one document. It resets to the fast
 * interval whenever anything actually changes, so the tail of a long ingest is
 * cheap while the moment a status flips stays responsive.
 */

/** Statuses that mean the worker has not finished with a document yet. */
const PENDING: ReadonlySet<string> = new Set(["pending", "processing"]);

const POLL_MIN_MS = 2000;
const POLL_MAX_MS = 30000;
const POLL_FACTOR = 1.5;

/** The only two fields the poll cares about — anything with an id and a status. */
export interface IngestingDocument {
  id: string;
  status: string;
}

export function usePollWhileIngesting(
  documents: readonly IngestingDocument[],
  refresh: () => void,
): void {
  const delayRef = useRef(POLL_MIN_MS);
  const signatureRef = useRef("");

  // The poll schedule depends on the documents and on nothing else. Holding the
  // callback in a ref keeps it out of the effect's dependencies, so a caller
  // passing an inline arrow — the obvious way to write `() => refresh(id)` —
  // does not restart the timer on every render and stall the poll forever.
  const refreshRef = useRef(refresh);
  useEffect(() => {
    refreshRef.current = refresh;
  });

  useEffect(() => {
    // Ids and statuses, order-independent: a new document appearing and a
    // status flipping are both "something happened", and both mean the next
    // poll should be a fast one.
    const signature = documents
      .map((document) => `${document.id}:${document.status}`)
      .sort()
      .join("|");
    if (signature !== signatureRef.current) {
      signatureRef.current = signature;
      delayRef.current = POLL_MIN_MS;
    }

    if (!documents.some((document) => PENDING.has(document.status))) return;

    const timeout = setTimeout(() => {
      delayRef.current = Math.min(Math.round(delayRef.current * POLL_FACTOR), POLL_MAX_MS);
      refreshRef.current();
    }, delayRef.current);
    return () => clearTimeout(timeout);
  }, [documents]);
}
