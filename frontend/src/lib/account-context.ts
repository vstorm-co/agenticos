/**
 * What every agent is told about the person, when an agent saved it for them (#2301).
 *
 * AgenticOS's welcome interview ends with `set_my_profile`; the open console then
 * shows the saved role and work in Settings -> Profile without a reload, the way
 * `account-locale.ts` switches the language for `set_my_language`.
 */

import { useAuthStore } from "@/stores";

/** The platform's own tool, by the exact name a run gives it - see `account-locale.ts`. */
const SET_MY_PROFILE = "agenticos_set_my_profile";

export interface AgentContextFields {
  job_title: string | null;
  about: string | null;
}

/**
 * The role and work an agent's tool call just saved, or null when it saved none.
 *
 * The result is the API's answer, `{"job_title": ..., "about": ...}`; anything
 * else is a refusal the model reads, and changes nothing here.
 */
export function contextSavedBy(toolName: string, result: string): AgentContextFields | null {
  if (toolName !== SET_MY_PROFILE) return null;
  try {
    const parsed: unknown = JSON.parse(result);
    if (!parsed || typeof parsed !== "object" || !("job_title" in parsed) || !("about" in parsed)) {
      return null;
    }
    const field = (value: unknown) => (typeof value === "string" ? value : null);
    return { job_title: field(parsed.job_title), about: field(parsed.about) };
  } catch {
    return null;
  }
}

/** Record what was saved on the signed-in account, in this tab. */
export function adoptAccountContext(fields: AgentContextFields): void {
  const { user, setUser } = useAuthStore.getState();
  if (user) setUser({ ...user, ...fields });
}
