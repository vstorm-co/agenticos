/**
 * How many categories and tags one agent may carry - `MAX_CATEGORIES` and
 * `MAX_TAGS` in `backend/app/schemas/agent.py`.
 *
 * The same bounds cap a discovery filter: `normalize_labels_query` keeps only
 * this many of each and drops the rest without saying so, so a filter offering
 * more would claim picks that have no effect.
 */
export const MAX_AGENT_CATEGORIES = 10;
export const MAX_AGENT_TAGS = 20;
