"use client";
import { ProfileIdentitySettings } from "@/components/settings/profile-identity-settings";
import { AppearanceSettings } from "@/components/settings/appearance-settings";
import { PersonalIntegrationAccounts } from "@/components/settings/personal-integration-accounts";
import { CodingAccounts } from "@/components/settings/coding-accounts";
import { ChatAccounts } from "@/components/settings/chat-accounts";
import { ForgetMe } from "@/components/memory/forget-me";
import { useAuth } from "@/hooks";
export default function ProfileSettingsPage() {
  const { user } = useAuth();
  if (!user) return null;
  return (
    <div className="grid min-w-0 flex-1 content-start gap-5 xl:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
      <div className="bg-card rounded-2xl border px-5 pb-2 sm:px-6 xl:col-span-2">
        <ProfileIdentitySettings unifiedSave />
      </div>
      <div className="bg-card min-w-0 rounded-2xl border px-5 pb-2 sm:px-6">
        <AppearanceSettings />
      </div>
      <div className="bg-card min-w-0 self-start rounded-2xl border px-5 pb-2 sm:px-6">
        <PersonalIntegrationAccounts />
        <ChatAccounts />
        <CodingAccounts />
      </div>
      <div className="xl:col-span-2">
        <ForgetMe userId={user.id} />
      </div>
    </div>
  );
}
