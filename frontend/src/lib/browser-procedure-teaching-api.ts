import { apiClient } from "@/lib/api-client";
import {
  browserCredentialRequest,
  isBrowserCredentialAudienceCurrent,
  type BrowserCredentialAudience,
} from "@/lib/browser-credentials-api";
import type {
  BrowserProcedureTeaching,
  BrowserProcedureTeachingStart,
  BrowserProcedureTeachingChange,
  BrowserProcedureTeachingPropose,
  BrowserProcedureTeachingPolicy,
  BrowserProcedureTeachingPreference,
  BrowserProcedureTeachingToggle,
  BrowserProcedureTeachingList,
} from "@/types/browser-procedure-teaching";
import type { SkillList } from "@/types/providers";

// Both browser features use the same owner/organization fence, including the
// abort latch for A -> B -> A identity changes. Do not retry a consent write.
export type BrowserProcedureTeachingAudience = BrowserCredentialAudience;
export const isBrowserProcedureTeachingAudienceCurrent = isBrowserCredentialAudienceCurrent;
const root = "/browser-procedures/teachings";
const path = (id: string) => `${root}/${encodeURIComponent(id)}`;
const preferencePath = (agentId: string) =>
  `/agents/${encodeURIComponent(agentId)}/browser-teaching-preference`;

export function listBrowserProcedureTeachings(
  audience: BrowserProcedureTeachingAudience,
  cursor: string | null,
  signal?: AbortSignal,
) {
  return browserCredentialRequest(
    audience,
    (options) =>
      apiClient.get<BrowserProcedureTeachingList>(root, {
        ...options,
        params: cursor !== null ? { limit: "20", cursor } : { limit: "20" },
      }),
    signal,
  );
}

export function readBrowserProcedureTeaching(
  audience: BrowserProcedureTeachingAudience,
  id: string,
  signal?: AbortSignal,
) {
  return browserCredentialRequest(
    audience,
    (options) => apiClient.get<BrowserProcedureTeaching>(path(id), options),
    signal,
  );
}
export function startBrowserProcedureTeaching(
  audience: BrowserProcedureTeachingAudience,
  body: BrowserProcedureTeachingStart,
  targetSkillId: string | null,
) {
  return browserCredentialRequest(audience, (options) =>
    apiClient.post<BrowserProcedureTeaching>(
      targetSkillId
        ? `/skills/${encodeURIComponent(targetSkillId)}/browser-procedures/teachings`
        : root,
      body,
      { ...options, retryAfterRefresh: false },
    ),
  );
}
export function changeBrowserProcedureTeaching(
  audience: BrowserProcedureTeachingAudience,
  id: string,
  revision: number,
  body: BrowserProcedureTeachingChange,
) {
  return browserCredentialRequest(audience, (options) =>
    apiClient.patch<BrowserProcedureTeaching>(path(id), body, {
      ...options,
      headers: { ...options.headers, "If-Match": `"${revision}"` },
      retryAfterRefresh: false,
    }),
  );
}
export function stopBrowserProcedureTeaching(
  audience: BrowserProcedureTeachingAudience,
  id: string,
) {
  return browserCredentialRequest(audience, (options) =>
    apiClient.post<BrowserProcedureTeaching>(
      `${path(id)}/stop`,
      {},
      { ...options, retryAfterRefresh: false },
    ),
  );
}
export function discardBrowserProcedureTeaching(
  audience: BrowserProcedureTeachingAudience,
  id: string,
) {
  return browserCredentialRequest(audience, (options) =>
    apiClient.delete<BrowserProcedureTeaching>(path(id), { ...options, retryAfterRefresh: false }),
  );
}
export function proposeBrowserProcedureTeaching(
  audience: BrowserProcedureTeachingAudience,
  id: string,
  revision: number,
  body: BrowserProcedureTeachingPropose,
) {
  return browserCredentialRequest(audience, (options) =>
    apiClient.post<BrowserProcedureTeaching>(`${path(id)}/propose`, body, {
      ...options,
      headers: { ...options.headers, "If-Match": `"${revision}"` },
      retryAfterRefresh: false,
    }),
  );
}
export function readBrowserProcedureTeachingPolicy(
  audience: BrowserProcedureTeachingAudience,
  signal?: AbortSignal,
) {
  return browserCredentialRequest(
    audience,
    (options) => apiClient.get<BrowserProcedureTeachingPolicy>("/browser-teaching-policy", options),
    signal,
  );
}
export function updateBrowserProcedureTeachingPolicy(
  audience: BrowserProcedureTeachingAudience,
  body: BrowserProcedureTeachingToggle,
) {
  return browserCredentialRequest(audience, (options) =>
    apiClient.put<BrowserProcedureTeachingPolicy>("/browser-teaching-policy", body, {
      ...options,
      retryAfterRefresh: false,
    }),
  );
}
export function readBrowserProcedureTeachingPreference(
  audience: BrowserProcedureTeachingAudience,
  agentId: string,
  signal?: AbortSignal,
) {
  return browserCredentialRequest(
    audience,
    (options) =>
      apiClient.get<BrowserProcedureTeachingPreference>(preferencePath(agentId), options),
    signal,
  );
}
export function updateBrowserProcedureTeachingPreference(
  audience: BrowserProcedureTeachingAudience,
  agentId: string,
  body: BrowserProcedureTeachingToggle,
) {
  return browserCredentialRequest(audience, (options) =>
    apiClient.put<BrowserProcedureTeachingPreference>(preferencePath(agentId), body, {
      ...options,
      retryAfterRefresh: false,
    }),
  );
}
/** Resolve only this addressed run; never borrow the agent from another tab/chat. */
export function readBrowserProcedureTeachingRun(
  audience: BrowserProcedureTeachingAudience,
  runId: string,
  signal?: AbortSignal,
) {
  return browserCredentialRequest(
    audience,
    (options) =>
      apiClient.get<{ id: string; agent_id: string | null }>(
        `/runs/${encodeURIComponent(runId)}`,
        options,
      ),
    signal,
  );
}
export function readBrowserProcedureTeachingSkills(
  audience: BrowserProcedureTeachingAudience,
  skip: number,
  signal?: AbortSignal,
) {
  return browserCredentialRequest(
    audience,
    (options) =>
      apiClient.get<SkillList>("/skills", {
        ...options,
        params: { skip: String(skip), limit: "50", sort: "name" },
      }),
    signal,
  );
}
