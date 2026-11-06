import { apiClient } from "./api-client";

export interface PhoneChoice {
  id: string;
  label: string;
}
export interface PhoneEndpointConfig {
  enabled: boolean;
  inbound_embed_id: string | null;
  max_call_seconds: number;
  calls_per_hour: number;
  calls_per_day: number;
  max_concurrent: number;
  daily_budget_usd: string | number;
  price_per_minute_usd: string | number;
  transfer_contact_ids: string[];
}
export interface PhoneEndpoint extends PhoneEndpointConfig {
  id: string;
  bot_id: string;
  bot_name: string;
  inbound_url: string;
  status_url: string;
}
export type ReportLanguage = "en-US" | "pl-PL" | "de-DE" | "es-ES";
export const REPORT_LANGUAGES: ReportLanguage[] = ["en-US", "pl-PL", "de-DE", "es-ES"];
export function isReportLanguage(value: string): value is ReportLanguage {
  return REPORT_LANGUAGES.some((item) => item === value);
}
export interface PhoneContactConfig {
  identity_id: string;
  allow_calls: boolean;
  allow_reports: boolean;
  allow_transfers: boolean;
  agent_ids: string[];
  allow_important: boolean;
  importance_instructions: string;
  escalation_delay_seconds: number;
  report_language: ReportLanguage;
  timezone: string;
  quiet_start_hour: number;
  quiet_end_hour: number;
  calls_per_day: number;
}
export interface PhoneContact extends PhoneContactConfig {
  id: string;
  masked_number: string;
}
export interface PhoneSettings {
  endpoints: PhoneEndpoint[];
  contact: PhoneContact | null;
  sms_identities: PhoneChoice[];
  sms_bots: PhoneChoice[];
  public_voice_embeds: PhoneChoice[];
  transfer_contacts: PhoneChoice[];
  call_endpoints: PhoneChoice[];
}
export interface PhoneCall {
  purpose: string;
  outcome_id: string | null;
  not_before: string | null;
  id: string;
  endpoint_id: string;
  mode: string;
  direction: string;
  status: string;
  conversation_id: string | null;
  voice_call_id: string | null;
  estimated_cost_usd: string;
  created_at: string;
}
export interface PhoneCallCreate {
  request_key: string;
  endpoint_id: string;
  mode: "conversation" | "report";
  agent_id?: string | null;
  report?: string | null;
  source_conversation_id?: string | null;
}
export const phoneApi = {
  settings: () => apiClient.get<PhoneSettings>("/phone/settings"),
  saveContact: (data: PhoneContactConfig) =>
    apiClient.put<PhoneContact>("/phone/contact", contactPayload(data)),
  configure: (botId: string, data: PhoneEndpointConfig) =>
    apiClient.put<PhoneEndpoint>(`/phone/bots/${botId}`, endpointPayload(data)),
  call: (data: PhoneCallCreate) => apiClient.post<PhoneCall>("/phone/calls", data),
  calls: () => apiClient.get<PhoneCall[]>("/phone/calls"),
  receipt: (id: string) => apiClient.get<PhoneCall>(`/phone/calls/${id}`),
  hangup: (id: string) => apiClient.post<void>(`/phone/calls/${id}/hangup`, {}),
  transferOptions: (id: string) =>
    apiClient.get<PhoneChoice[]>(`/phone/calls/${id}/transfer-options`),
  transfer: (id: string, contactId: string) =>
    apiClient.post<void>(`/phone/calls/${id}/transfer`, { contact_id: contactId }),
};
export const endedPhoneStatuses = new Set(["completed", "failed", "cancelled"]);

function contactPayload(data: PhoneContactConfig): PhoneContactConfig {
  return {
    identity_id: data.identity_id,
    allow_calls: data.allow_calls,
    allow_reports: data.allow_reports,
    allow_transfers: data.allow_transfers,
    agent_ids: data.agent_ids,
    allow_important: data.allow_important,
    importance_instructions: data.importance_instructions,
    escalation_delay_seconds: data.escalation_delay_seconds,
    report_language: data.report_language,
    timezone: data.timezone,
    quiet_start_hour: data.quiet_start_hour,
    quiet_end_hour: data.quiet_end_hour,
    calls_per_day: data.calls_per_day,
  };
}
function endpointPayload(data: PhoneEndpointConfig): PhoneEndpointConfig {
  return {
    enabled: data.enabled,
    inbound_embed_id: data.inbound_embed_id,
    max_call_seconds: data.max_call_seconds,
    calls_per_hour: data.calls_per_hour,
    calls_per_day: data.calls_per_day,
    max_concurrent: data.max_concurrent,
    daily_budget_usd: data.daily_budget_usd,
    price_per_minute_usd: data.price_per_minute_usd,
    transfer_contact_ids: data.transfer_contact_ids,
  };
}
