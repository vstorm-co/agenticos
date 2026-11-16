"use client";
import { ProfileIdentitySettings } from "@/components/settings/profile-identity-settings";
import { AppearanceSettings } from "@/components/settings/appearance-settings";
import { CodingAccounts } from "@/components/settings/coding-accounts";
import { ChatAccounts } from "@/components/settings/chat-accounts";
import { ForgetMe } from "@/components/memory/forget-me";
import { useAuth } from "@/hooks";
export default function ProfileSettingsPage() {
  const { user } = useAuth();
  if (!user) return null;
  return (
    <div className="grid min-w-0 flex-1 content-start gap-5">
      <div className="bg-card rounded-2xl border px-5 pb-2 sm:px-6">
        <ProfileIdentitySettings unifiedSave />
      </div>
      <div className="bg-card min-w-0 self-start rounded-2xl border px-5 pb-2 sm:px-6">
        <ChatAccounts />
        <CodingAccounts />
      </div>
      <div className="bg-card min-w-0 rounded-2xl border px-5 pb-2 sm:px-6">
        <AppearanceSettings />
      </div>
      <div>
        <ForgetMe userId={user.id} />
      </div>
    </div>
  );
}
