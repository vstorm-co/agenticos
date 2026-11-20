import { apiClient } from "@/lib/api-client";

export type SourceProvider = "webhook" | "github" | "linear" | "hubspot" | "zendesk";
export type SourceAuthMethod = "provider" | "hmac" | "basic" | "api_key" | "standard_webhooks";
export interface SourceAuth {
  method: SourceAuthMethod;
  header_name?: string;
  signature_prefix?: string;
  encoding?: "hex" | "base64" | "base64url";
  legacy?: boolean;
}
export interface SourceCredentials {
  secret?: string;
  username?: string;
  password?: string;
}
export interface EventSource {
  id: string;
  name: string;
  provider: SourceProvider;
  auth: SourceAuth;
  delivery_id_header: string | null;
  visibility: "private" | "org";
  owner_user_id: string | null;
  is_active: boolean;
  webhook_url: string;
  can_use: boolean;
  can_edit: boolean;
}
export interface EventSourceCreate {
  name: string;
  provider: SourceProvider;
  auth: SourceAuth;
  visibility: "private" | "org";
  delivery_id_header?: string | null;
  credentials: SourceCredentials;
}
export interface EventSourceCreated extends EventSource {
  reveal_secret?: string | null;
}
export interface EventSample {
  body: Record<string, unknown>;
  delivery_id: string;
}
export interface SourceListening {
  listener_id: string;
  expires_at: string;
}
export interface SourceCapture {
  state: "listening" | "caught" | "expired" | "too_large";
  delivery?: EventSample | null;
}
export interface SourceUsage {
  items: {
    id: string;
    kind: "routine" | "workflow";
    target_id: string | null;
    name: string;
    is_active: boolean | null;
  }[];
  total: number;
}
const base = "/event-sources";

async function listEventSources(): Promise<{ items: EventSource[]; total: number }> {
  const first = await apiClient.get<{ items: EventSource[]; total: number }>(base);
  const items = [...first.items];
  while (items.length < first.total) {
    const page = await apiClient.get<{ items: EventSource[]; total: number }>(base, {
      params: { skip: String(items.length), limit: "100" },
    });
    if (!page.items.length) break;
    items.push(...page.items);
  }
  return { ...first, items };
}

export const eventSourcesApi = {
  list: listEventSources,
  get: (id: string) => apiClient.get<EventSource>(`${base}/${id}`),
  create: (input: EventSourceCreate) => apiClient.post<EventSourceCreated>(base, input),
  update: (
    id: string,
    input: Partial<Omit<EventSourceCreate, "provider">> & { is_active?: boolean },
  ) => apiClient.patch<EventSource>(`${base}/${id}`, input),
  remove: (id: string) => apiClient.delete<void>(`${base}/${id}`),
  credentials: (id: string, credentials: SourceCredentials) =>
    apiClient.post<void>(`${base}/${id}/credentials`, credentials),
  usage: (id: string) => apiClient.get<SourceUsage>(`${base}/${id}/usage`),
  listen: (id: string) => apiClient.post<SourceListening>(`${base}/${id}/listen`, {}),
  capture: (id: string, token: string) =>
    apiClient.get<SourceCapture>(`${base}/${id}/listen/${token}`),
  preview: (
    agentId: string,
    input: {
      prompt: string;
      payload: Record<string, unknown>;
      result_mode: "report" | "inbox";
      source_id?: string;
      trigger_id?: string;
    },
  ) =>
    apiClient.post<{ resolved_prompt: string }>(
      `/agents/${agentId}/triggers/preview-prompt`,
      input,
    ),
};
