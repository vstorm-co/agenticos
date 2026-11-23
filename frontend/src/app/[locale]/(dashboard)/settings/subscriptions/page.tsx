"use client";

import { SubscriptionAccounts } from "@/components/settings/subscription-accounts";

export default function SubscriptionSettingsPage() {
  return (
    <div className="bg-card flex min-h-0 min-w-0 flex-1 flex-col rounded-2xl border px-5 pb-2 sm:px-6">
      <SubscriptionAccounts />
    </div>
  );
}
