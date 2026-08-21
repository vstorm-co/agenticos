/**
 * The three constants reranking is configured with, in one place because two
 * surfaces set it: the create dialog and the detail page's edit dialog. Keeping
 * them apart is how the two drift - one dialog offering a model the other does
 * not, a purpose filter that stops matching the key it stored.
 *
 * All three mirror the backend. `RERANK_KEY_PURPOSE` is the single entry in
 * `RERANK_KEY_PURPOSES` (`app/services/rerank_resolution.py`); `DEFAULT_RERANK_MODEL`
 * is the value stored as `rerank_model`. No endpoint lists rerankers - there is
 * one - so the model is a constant rather than a fetched list.
 */

/** The purpose a vault key must carry to pay for reranking. */
export const RERANK_KEY_PURPOSE = "cohere";

/** Sentinel for "no reranking" - a Select item may not have an empty value. */
export const RERANK_OFF = "__off__";

/** The one reranker there is, stored as the collection's `rerank_model`. */
export const DEFAULT_RERANK_MODEL = "rerank-v3.5";
