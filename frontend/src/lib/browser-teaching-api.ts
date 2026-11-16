import { apiClient } from "@/lib/api-client";
import {
  browserCredentialRequest,
  isBrowserCredentialAudienceCurrent,
  type BrowserCredentialAudience,
} from "@/lib/browser-credentials-api";
import type {
  BrowserTeaching,
  TeachingStart,
  TeachingChange,
  TeachingPropose,
  TeachingPolicy,
  TeachingPreference,
  TeachingToggle,
  TeachingList,
} from "@/types/browser-teaching";
import type { SkillList } from "@/types/providers";

// Both browser features use the same owner/organization fence, including the
// abort latch for A -> B -> A identity changes. Do not retry a consent write.
export type TeachingAudience = BrowserCredentialAudience;
export const isTeachingAudienceCurrent = isBrowserCredentialAudienceCurrent;
const root = "/browser-teachings";
const path = (id: string) => `${root}/${encodeURIComponent(id)}`;
const preferencePath = (agentId: string) =>
  `/agents/${encodeURIComponent(agentId)}/browser-teaching-preference`;

export function listBrowserTeachings(
  audience: TeachingAudience,
  cursor: string | null,
  signal?: AbortSignal,
) {
  return browserCredentialRequest(
    audience,
    (options) =>
      apiClient.get<TeachingList>(root, {
        ...options,
        params: cursor !== null ? { limit: "20", cursor } : { limit: "20" },
      }),
    signal,
  );
}

export function readBrowserTeaching(audience: TeachingAudience, id: string, signal?: AbortSignal) {
  return browserCredentialRequest(
    audience,
    (options) => apiClient.get<BrowserTeaching>(path(id), options),
    signal,
  );
}
export function startBrowserTeaching(
  audience: TeachingAudience,
  body: TeachingStart,
  targetSkillId: string | null,
) {
  return browserCredentialRequest(audience, (options) =>
    apiClient.post<BrowserTeaching>(
      targetSkillId ? `/skills/${encodeURIComponent(targetSkillId)}/browser-teachings` : root,
      body,
      { ...options, retryAfterRefresh: false },
    ),
  );
}
export function changeBrowserTeaching(
  audience: TeachingAudience,
  id: string,
  revision: number,
  body: TeachingChange,
) {
  return browserCredentialRequest(audience, (options) =>
    apiClient.patch<BrowserTeaching>(path(id), body, {
      ...options,
      headers: { ...options.headers, "If-Match": `"${revision}"` },
      retryAfterRefresh: false,
    }),
  );
}
export function stopBrowserTeaching(audience: TeachingAudience, id: string) {
  return browserCredentialRequest(audience, (options) =>
    apiClient.post<BrowserTeaching>(
      `${path(id)}/stop`,
      {},
      { ...options, retryAfterRefresh: false },
    ),
  );
}
export function discardBrowserTeaching(audience: TeachingAudience, id: string) {
  return browserCredentialRequest(audience, (options) =>
    apiClient.delete<BrowserTeaching>(path(id), { ...options, retryAfterRefresh: false }),
  );
}
export function proposeBrowserTeaching(
  audience: TeachingAudience,
  id: string,
  revision: number,
  body: TeachingPropose,
) {
  return browserCredentialRequest(audience, (options) =>
    apiClient.post<BrowserTeaching>(`${path(id)}/propose`, body, {
      ...options,
      headers: { ...options.headers, "If-Match": `"${revision}"` },
      retryAfterRefresh: false,
    }),
  );
}
export function readTeachingPolicy(audience: TeachingAudience, signal?: AbortSignal) {
  return browserCredentialRequest(
    audience,
    (options) => apiClient.get<TeachingPolicy>("/browser-teaching-policy", options),
    signal,
  );
}
export function updateTeachingPolicy(audience: TeachingAudience, body: TeachingToggle) {
  return browserCredentialRequest(audience, (options) =>
    apiClient.put<TeachingPolicy>("/browser-teaching-policy", body, {
      ...options,
      retryAfterRefresh: false,
    }),
  );
}
export function readTeachingPreference(
  audience: TeachingAudience,
  agentId: string,
  signal?: AbortSignal,
) {
  return browserCredentialRequest(
    audience,
    (options) => apiClient.get<TeachingPreference>(preferencePath(agentId), options),
    signal,
  );
}
export function updateTeachingPreference(
  audience: TeachingAudience,
  agentId: string,
  body: TeachingToggle,
) {
  return browserCredentialRequest(audience, (options) =>
    apiClient.put<TeachingPreference>(preferencePath(agentId), body, {
      ...options,
      retryAfterRefresh: false,
    }),
  );
}
/** Resolve only this addressed run; never borrow the agent from another tab/chat. */
export function readTeachingRun(audience: TeachingAudience, runId: string, signal?: AbortSignal) {
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
export function readTeachingSkills(audience: TeachingAudience, skip: number, signal?: AbortSignal) {
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
