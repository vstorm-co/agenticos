"use client";

import { ConnectedApps } from "@/components/settings/connected-apps";
import { McpConnect } from "@/components/settings/mcp-connect";

export default function McpClientsSettingsPage() {
  return (
    <div className="flex flex-1 flex-col space-y-6">
      <McpConnect />
      <ConnectedApps />
    </div>
  );
}
