"use client";

import { ApiKeysManager } from "@/components/settings/api-keys-manager";
import { ConnectedApps } from "@/components/settings/connected-apps";

export default function ApiKeysSettingsPage() {
  return (
    <div className="space-y-6">
      <ApiKeysManager />
      <ConnectedApps />
    </div>
  );
}
