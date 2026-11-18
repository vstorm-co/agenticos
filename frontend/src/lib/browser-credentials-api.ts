import { apiClient } from "@/lib/api-client";
import { useAuthStore } from "@/stores/auth-store";
import { useOrgStore } from "@/stores/org-store";
import type {
  BrowserCredentialEligible,
  BrowserCredentialPlan,
  BrowserCredentialPolicy,
  BrowserCredentialPolicyEdit,
} from "@/types/browser-credentials";

export interface BrowserCredentialAudience {
  actor: string | undefined;
  organization: string | null;
}
type BrowserRequestOptions = {
  signal: AbortSignal;
  cache: "no-store";
  headers: Record<string, string>;
};

export function isBrowserCredentialAudienceCurrent(
  audience: BrowserCredentialAudience | undefined,
): boolean {
  return (
    !!audience?.actor &&
    !!audience.organization &&
    useAuthStore.getState().user?.id === audience.actor &&
    useOrgStore.getState().activeOrgId === audience.organization
  );
}

/** Stop old reads and writes on identity changes; an aborted write is still an uncertain attempt. */
export async function browserCredentialRequest<T>(
  audience: BrowserCredentialAudience,
  send: (options: BrowserRequestOptions) => Promise<T>,
  signal?: AbortSignal,
): Promise<T> {
  const controller = new AbortController();
  const abort = () => controller.abort();
  const check = () => {
    if (!isBrowserCredentialAudienceCurrent(audience)) abort();
  };
  const unsubscribeAuth = useAuthStore.subscribe(check);
  const unsubscribeOrg = useOrgStore.subscribe(check);
  signal?.addEventListener("abort", abort, { once: true });
  if (signal?.aborted) abort();
  check();
  try {
    if (controller.signal.aborted) {
      // i18n-exempt: an internal cancellation, never user-facing copy.
      throw new DOMException("Browser credential audience changed", "AbortError");
    }
    const result = await send({
      signal: controller.signal,
      cache: "no-store",
      headers: { "X-Organization-Id": audience.organization! },
    });
    if (controller.signal.aborted || !isBrowserCredentialAudienceCurrent(audience)) {
      // i18n-exempt: prevents a delayed response from entering another audience's cache.
      throw new DOMException("Browser credential audience changed", "AbortError");
    }
    return result;
  } finally {
    unsubscribeAuth();
    unsubscribeOrg();
    signal?.removeEventListener("abort", abort);
  }
}

const policyPath = (id: string) => `/secrets/${encodeURIComponent(id)}/browser-policy`;
const planPath = (runId: string, planId: string) =>
  `/runs/${encodeURIComponent(runId)}/browser-credential-plans/${encodeURIComponent(planId)}`;

export function readBrowserCredentialEligibility(
  audience: BrowserCredentialAudience,
  runId: string,
  callId: string,
  tabId: string,
  signal?: AbortSignal,
) {
  return browserCredentialRequest(
    audience,
    (options) =>
      apiClient.get<BrowserCredentialEligible[]>(
        `/runs/${encodeURIComponent(runId)}/browser-credentials`,
        { ...options, params: { call_id: callId, tab_id: tabId } },
      ),
    signal,
  );
}

export function readBrowserCredentialPolicy(
  audience: BrowserCredentialAudience,
  secretId: string,
  signal?: AbortSignal,
) {
  return browserCredentialRequest(
    audience,
    (options) => apiClient.get<BrowserCredentialPolicy>(policyPath(secretId), options),
    signal,
  );
}
export function updateBrowserCredentialPolicy(
  audience: BrowserCredentialAudience,
  secretId: string,
  body: BrowserCredentialPolicyEdit,
) {
  return browserCredentialRequest(audience, (options) =>
    apiClient.put<BrowserCredentialPolicy>(policyPath(secretId), body, {
      ...options,
      retryAfterRefresh: false,
    }),
  );
}
export function readBrowserCredentialPlan(
  audience: BrowserCredentialAudience,
  runId: string,
  planId: string,
  signal?: AbortSignal,
) {
  return browserCredentialRequest(
    audience,
    (options) => apiClient.get<BrowserCredentialPlan>(planPath(runId, planId), options),
    signal,
  );
}
export function confirmBrowserCredentialPlan(
  audience: BrowserCredentialAudience,
  plan: BrowserCredentialPlan,
  approve: boolean,
) {
  return browserCredentialRequest(audience, (options) =>
    apiClient.post<BrowserCredentialPlan>(
      `${planPath(plan.run_id, plan.id)}/confirmation`,
      {
        document_id: plan.document_id,
        authorization_generation: plan.authorization_generation,
        approve,
      },
      { ...options, retryAfterRefresh: false },
    ),
  );
}
export function readBrowserCredentialSubmission(
  audience: BrowserCredentialAudience,
  runId: string,
  parentId: string,
  signal?: AbortSignal,
) {
  return browserCredentialRequest(
    audience,
    (options) =>
      apiClient.get<BrowserCredentialPlan | null>(
        `${planPath(runId, parentId)}/submission`,
        options,
      ),
    signal,
  );
}
export interface BrowserSubmissionAttempt {
  request_id: string;
  document_id: string;
  authorization_generation: string;
}
export function submitBrowserCredentialPlan(
  audience: BrowserCredentialAudience,
  runId: string,
  parentId: string,
  attempt: BrowserSubmissionAttempt,
) {
  return browserCredentialRequest(audience, (options) =>
    apiClient.post<BrowserCredentialPlan>(`${planPath(runId, parentId)}/submission`, attempt, {
      ...options,
      retryAfterRefresh: false,
    }),
  );
}
