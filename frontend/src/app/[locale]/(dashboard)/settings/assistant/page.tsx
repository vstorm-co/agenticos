"use client";

import { AssistantSettings } from "@/components/assistant/assistant-settings";

/**
 * The AI Architect (#2063). Under `/settings/` because half of it is yours - the
 * tips it shows you - and the other half, its name and model, is shown only to
 * somebody who may change the organization's settings.
 */
export default function AssistantSettingsPage() {
  return <AssistantSettings />;
}
