/**
 * What a RAG or sync status is drawn as - the one place that knows the tokens.
 *
 * Three columns share one vocabulary between them and nothing joined them up:
 *
 * | Column | What the worker writes |
 * |---|---|
 * | `rag_documents.status` | `processing`, `done`, `error` |
 * | `sync_sources.last_sync_status` | `done`, `error` |
 * | `sync_logs.status` | `running`, `done`, `error`, `cancelled` |
 *
 * Four places compared against those values and three compared against words
 * nothing writes. `SyncStatusBadge` tested `status === "failed"`, so a failed
 * sync source was drawn in the same muted grey as a finished one with the raw
 * token `error` for a label (#356). `StatusBadge` beside it mapped `completed`,
 * `pending` and `failed`, none of which reach a `RAGDocument`, so every
 * document on the Knowledge Base page fell through to its raw token too - the
 * badge #356 held up as the one that had been fixed. And `/rag` drew anything
 * it did not recognise as a spinner, which is how a **cancelled** sync went on
 * spinning for the life of the page.
 *
 * A literal repeated in four components is four chances to drift, and it drifted
 * in three. So the tokens live here, once, and a component asks rather than
 * guesses.
 *
 * The value is not narrowed to a union anywhere it crosses the wire, and that is
 * deliberate: the column is a free `String(20)` that no constraint holds to this
 * list, so {@link ragStatus} answers `unknown` for a value this build has never
 * heard of and the badge falls through to the server's own token. Inventing a
 * word for it would be the same mistake one layer down.
 */

/** How a status should read, independently of which control is drawing it. */
export type RAGStatusTone =
  /** Under way - `processing`, `running`. */
  | "progress"
  /** Finished, and nothing went wrong. */
  | "success"
  /** Finished, and something did. */
  | "failure"
  /** Stopped on purpose, which is neither of the two above. */
  | "cancelled"
  /** A token this build does not know. Show it verbatim; claim nothing. */
  | "unknown";

/** A status, resolved into something a control can draw. */
export interface RAGStatusPresentation {
  /**
   * The key under the `ragStatus` message namespace, or `null` when the status
   * is one this build does not know.
   *
   * A key rather than a word because a module-level table cannot call a
   * translator - the component translates at the point of use.
   */
  readonly words: string | null;
  readonly tone: RAGStatusTone;
}

const KNOWN: Readonly<Record<string, RAGStatusPresentation>> = {
  processing: { words: "processing", tone: "progress" },
  running: { words: "running", tone: "progress" },
  done: { words: "done", tone: "success" },
  error: { words: "error", tone: "failure" },
  cancelled: { words: "cancelled", tone: "cancelled" },
};

const UNKNOWN: RAGStatusPresentation = { words: null, tone: "unknown" };

/**
 * Resolve a status the server sent into a word to say and a tone to say it in.
 *
 * Total on purpose: a caller never has to decide what to do about a token this
 * build has not heard of, because deciding separately in each control is how
 * three of the four came to disagree.
 */
export function ragStatus(status: string): RAGStatusPresentation {
  return KNOWN[status] ?? UNKNOWN;
}
