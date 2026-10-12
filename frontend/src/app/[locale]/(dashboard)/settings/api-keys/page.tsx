"use client";

import { ApiKeysManager } from "@/components/settings/api-keys-manager";
import { ApiUsage } from "@/components/settings/api-usage";

export default function ApiKeysSettingsPage() {
  return (
    <div className="space-y-6">
      <ApiUsage />
      <ApiKeysManager />
    </div>
  );
}
