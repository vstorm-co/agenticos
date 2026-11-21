"use client";

import { SubscriptionAccounts } from "@/components/settings/subscription-accounts";

export default function SubscriptionSettingsPage() {
  return (
    <div className="bg-card min-w-0 rounded-2xl border px-5 pb-2 sm:px-6">
      <SubscriptionAccounts />
    </div>
  );
}
