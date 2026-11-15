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
    <div className="flex flex-1 flex-col space-y-4">
      <ProfileIdentitySettings />
      <AppearanceSettings />
      <ChatAccounts />
      <CodingAccounts />
      <ForgetMe userId={user.id} />
    </div>
  );
}
