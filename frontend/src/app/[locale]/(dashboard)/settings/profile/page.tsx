"use client";

import Image from "next/image";
import { useEffect, useRef, useState } from "react";
import { Camera } from "lucide-react";
import { toast } from "sonner";

import { Button, FormField, Input } from "@/components/ui";
import { ActiveSessions } from "@/components/dashboard/active-sessions";
import { SectionCard } from "@/components/settings/settings-section";
import { useAuth } from "@/hooks";
import { apiClient, ApiError } from "@/lib/api-client";
import { formatDate, getErrorMessage, isAppAdmin, MAX_AVATAR_SIZE_BYTES } from "@/lib/utils";
import { useAuthStore } from "@/stores";
import type { User } from "@/types";

export default function ProfileSettingsPage() {
  const { user } = useAuth();
  const { setUser, bumpAvatarVersion, avatarVersion } = useAuthStore();

  const [name, setName] = useState(user?.full_name ?? "");
  const [email, setEmail] = useState(user?.email ?? "");
  const [saving, setSaving] = useState(false);
  const [avatarUploading, setAvatarUploading] = useState(false);
  const avatarInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setName(user?.full_name ?? "");
    setEmail(user?.email ?? "");
  }, [user?.id, user?.email, user?.full_name]);

  const handleSaveProfile = async () => {
    if (!user) return;
    setSaving(true);
    try {
      const payload: { email?: string; full_name?: string | null } = {};
      if (email !== user.email) payload.email = email;
      if (name !== (user.full_name ?? "")) payload.full_name = name || null;
      if (Object.keys(payload).length === 0) {
        toast.info("Nothing changed");
        setSaving(false);
        return;
      }
      const updated = await apiClient.patch<User>("/users/me", payload);
      setUser(updated);
      toast.success("Profile updated");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Failed to update profile");
    } finally {
      setSaving(false);
    }
  };

  const handleAvatarUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    e.target.value = "";
    if (file.size > MAX_AVATAR_SIZE_BYTES) {
      toast.error("Avatar too large. Maximum 2MB.");
      return;
    }
    setAvatarUploading(true);
    try {
      const formData = new FormData();
      formData.append("file", file);
      const res = await fetch("/api/users/me/avatar", { method: "POST", body: formData });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Upload failed" }));
        throw new Error(err.detail || "Upload failed");
      }
      const updated = await res.json();
      setUser(updated);
      bumpAvatarVersion();
      toast.success("Avatar updated");
    } catch (err) {
      toast.error(getErrorMessage(err, "Failed to upload avatar"));
    } finally {
      setAvatarUploading(false);
    }
  };

  if (!user) {
    return null;
  }

  return (
    <div className="space-y-6">
      <SectionCard
        title="Avatar"
        description="Square images look best. Up to 2MB. JPG, PNG, WEBP, or GIF."
      >
        <div className="flex items-center gap-5">
          <button
            type="button"
            onClick={() => avatarInputRef.current?.click()}
            disabled={avatarUploading}
            aria-label={user.avatar_url ? "Replace avatar" : "Upload avatar"}
            className="border-border bg-muted hover:bg-accent group relative flex h-20 w-20 shrink-0 items-center justify-center overflow-hidden rounded-xl border transition-colors"
          >
            {user.avatar_url ? (
              <Image
                src={`/api/users/avatar/${user.id}?v=${avatarVersion}`}
                alt=""
                width={80}
                height={80}
                className="h-full w-full object-cover"
                unoptimized
              />
            ) : (
              <span className="text-foreground text-lg font-semibold">
                {(user.full_name || user.email).slice(0, 2).toUpperCase()}
              </span>
            )}
            <span className="absolute inset-0 flex items-center justify-center bg-black/50 opacity-0 transition-opacity group-hover:opacity-100">
              <Camera className="h-5 w-5 text-white" />
            </span>
          </button>
          <input
            ref={avatarInputRef}
            type="file"
            accept="image/jpeg,image/png,image/webp,image/gif"
            onChange={handleAvatarUpload}
            className="hidden"
          />
          <div>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => avatarInputRef.current?.click()}
              disabled={avatarUploading}
            >
              {avatarUploading
                ? "Uploading…"
                : user.avatar_url
                  ? "Replace avatar"
                  : "Upload avatar"}
            </Button>
            <p className="text-muted-foreground mt-2 text-xs">
              {isAppAdmin(user) ? "Admin · " : ""}Member since {formatDate(user.created_at)}
            </p>
          </div>
        </div>
      </SectionCard>

      <SectionCard
        title="Personal info"
        description="Visible to teammates in shared organizations."
        action={
          <Button onClick={handleSaveProfile} disabled={saving} size="sm">
            {saving ? "Saving…" : "Save changes"}
          </Button>
        }
      >
        <div className="space-y-4">
          <FormField label="Display name" htmlFor="profile-name">
            <Input
              id="profile-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="How should we call you?"
            />
          </FormField>
          <FormField
            label="Email"
            htmlFor="profile-email"
            description="Changing email may require re-verification depending on your auth setup."
          >
            <Input
              id="profile-email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </FormField>
        </div>
      </SectionCard>

      <ActiveSessions />
    </div>
  );
}
