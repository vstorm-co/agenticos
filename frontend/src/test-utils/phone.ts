import type { PhoneSettings, PhoneCall, PhoneContactConfig } from "@/lib/phone-api";
export const phoneContact: PhoneContactConfig = {
  identity_id: "identity",
  allow_calls: false,
  allow_reports: false,
  allow_transfers: false,
  agent_ids: [],
  allow_important: false,
  importance_instructions: "",
  escalation_delay_seconds: 0,
  report_language: "en-US",
  timezone: "UTC",
  quiet_start_hour: 22,
  quiet_end_hour: 8,
  calls_per_day: 3,
};
export const phoneSettings: PhoneSettings = {
  contact: null,
  endpoints: [],
  sms_identities: [{ id: "identity", label: "••••1111" }],
  sms_bots: [{ id: "bot", label: "Telephone" }],
  public_voice_embeds: [],
  transfer_contacts: [],
  call_endpoints: [{ id: "endpoint", label: "Telephone" }],
};
export const phoneCall: PhoneCall = {
  id: "call",
  purpose: "direct",
  outcome_id: null,
  not_before: null,
  endpoint_id: "endpoint",
  mode: "conversation",
  direction: "outbound",
  status: "unknown",
  conversation_id: null,
  voice_call_id: null,
  estimated_cost_usd: "0.50",
  created_at: "2026-11-04T00:00:00Z",
};
