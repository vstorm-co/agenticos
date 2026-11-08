"use client";

import Image from "next/image";
import { useRef, useState } from "react";
import { Camera } from "lucide-react";
import { toast } from "sonner";

import { ApiError, getErrorMessage } from "@/lib/api-error";
import { AvatarColorPicker, Button, FormField, Input } from "@/components/ui";
import { AvatarFace } from "@/components/ui/avatar-face";
import { AgentContextSettings } from "@/components/settings/agent-context-settings";
import { SectionCard } from "@/components/settings/settings-section";
import { useAuth } from "@/hooks";
import { apiClient } from "@/lib/api-client";
import { cn, formatDate, isAppAdmin, MAX_AVATAR_SIZE_BYTES } from "@/lib/utils";
import { useAuthStore } from "@/stores";
import type { User } from "@/types";
import { useUploadAccountAvatar } from "@/hooks/use-account-profile";
import { useChanged } from "@/hooks/use-changed";
import { useLocale, useTranslations } from "next-intl";
import styles from "./profile-identity-settings.module.css";

export function ProfileIdentitySettings({
  onContinue,
  saveLabel,
  section = "all",
}: {
  onContinue?: () => void;
  saveLabel?: string;
  section?: "all" | "identity" | "context";
}) {
  const tErrors = useTranslations("errors");
  const t = useTranslations("pages.settings");
  const locale = useLocale();
  const { user } = useAuth();
  const { setUser, avatarVersion } = useAuthStore();

  const uploadAvatar = useUploadAccountAvatar();
  const [name, setName] = useState(user?.full_name ?? "");
  const [email, setEmail] = useState(user?.email ?? "");
  const [saving, setSaving] = useState(false);
  const [avatarUploading, setAvatarUploading] = useState(false);
  const avatarInputRef = useRef<HTMLInputElement>(null);

  // Re-seeded when the stored profile moves - a save coming back, or another
  // tab. During render, so a stale name is never shown in the field.
  if (useChanged(`${user?.id}|${user?.email}|${user?.full_name}`)) {
    setName(user?.full_name ?? "");
    setEmail(user?.email ?? "");
  }

  const handleSaveProfile = async () => {
    if (!user) return false;
    setSaving(true);
    try {
      const payload: { email?: string; full_name?: string | null } = {};
      if (email !== user.email) payload.email = email;
      if (name !== (user.full_name ?? "")) payload.full_name = name || null;
      if (Object.keys(payload).length === 0) {
        toast.info(t("nothingChanged"));
        setSaving(false);
        return true;
      }
      const updated = await apiClient.patch<User>("/users/me", payload);
      setUser(updated);
      if (payload.email !== undefined) setEmail(updated.email);
      // A new address is staged rather than applied, so the field re-seeds to
      // the address the account still has. Saying "profile updated" over that
      // reads as a change that silently did not take.
      //
      // Gated on this request having carried an address, not on the answer
      // holding one: a change staged an hour ago is still on every later
      // response, so saving only a display name would otherwise claim a
      // verification email had just been sent - most misleading right after one
      // failed to arrive.
      if (payload.email !== undefined && updated.pending_email) {
        toast.success(t("emailChangeSent", { email: updated.pending_email }));
      } else {
        toast.success(t("profileUpdated"));
      }
      return true;
    } catch (err) {
      toast.error(
        err instanceof ApiError ? getErrorMessage(err, tErrors) : t("failedUpdateProfile"),
      );
      return false;
    } finally {
      setSaving(false);
    }
  };

  const handleAvatarUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    e.target.value = "";
    if (file.size > MAX_AVATAR_SIZE_BYTES) {
      toast.error(t("avatarTooLargeMaximum2"));
      return;
    }
    setAvatarUploading(true);
    try {
      await uploadAvatar(file);
      toast.success(t("avatarUpdated"));
    } catch (err) {
      toast.error(getErrorMessage(err, tErrors, t("failedUploadAvatar2")));
    } finally {
      setAvatarUploading(false);
    }
  };

  const handleColorChange = async (slot: number | null) => {
    if (!user || slot === (user.avatar_color ?? null)) return;
    try {
      const updated = await apiClient.patch<User>("/users/me", { avatar_color: slot });
      setUser(updated);
    } catch (err) {
      toast.error(
        err instanceof ApiError ? getErrorMessage(err, tErrors) : t("failedUpdateProfile"),
      );
    }
  };

  if (!user) {
    return null;
  }
  const profileChanged = name !== (user.full_name ?? "") || email !== user.email;

  return (
    <div
      className={cn(
        "flex flex-1 flex-col space-y-4",
        onContinue && section === "identity" && styles.guided,
      )}
    >
      {section !== "context" && (
        <>
          <SectionCard title={t("avatar")} description={t("squareImagesLookBest")}>
            <div
              className={cn(
                "grid items-center gap-4 md:grid-cols-2",
                onContinue && styles.avatarEditor,
              )}
            >
              <div className={cn("flex items-center gap-4", onContinue && styles.portraitControls)}>
                <button
                  type="button"
                  onClick={() => avatarInputRef.current?.click()}
                  disabled={avatarUploading}
                  aria-label={user.avatar_url ? t("replaceAvatar3") : t("uploadAvatar3")}
                  className={cn(
                    "border-border hover:bg-accent group relative flex h-16 w-16 shrink-0 items-center justify-center overflow-hidden rounded-full border transition-colors",
                    user.avatar_url && "bg-muted",
                    onContinue && styles.portrait,
                  )}
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
                    // The same face every other screen draws for this person, at the
                    // size they are about to replace it. Showing initials here and a
                    // face everywhere else made this the one page that disagreed with
                    // the product about what somebody looks like.
                    <AvatarFace seed={user.id} colorSlot={user.avatar_color} />
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
                    data-guidance={
                      (!!onContinue && !user.avatar_url && user.avatar_color == null) || undefined
                    }
                  >
                    {avatarUploading
                      ? t("uploading3")
                      : user.avatar_url
                        ? t("replaceAvatar4")
                        : t("uploadAvatar4")}
                  </Button>
                  <p className="text-muted-foreground mt-2 text-xs">
                    {isAppAdmin(user) ? t("admin") : ""}
                    {t("memberSince", { date: formatDate(user.created_at, locale) })}
                  </p>
                </div>
              </div>
              <div>
                <p className="text-foreground mb-2 text-sm font-medium">{t("avatarColour")}</p>
                <p className="text-muted-foreground mb-3 text-xs">{t("avatarColourHint")}</p>
                <AvatarColorPicker
                  value={user.avatar_color ?? null}
                  onChange={handleColorChange}
                  className={onContinue ? "justify-center" : undefined}
                />
              </div>
            </div>
          </SectionCard>

          <SectionCard
            title={t("personalInfo")}
            description={t("visibleTeammatesSharedOrganizations")}
            action={
              !onContinue && (
                <Button onClick={handleSaveProfile} disabled={saving || !profileChanged} size="sm">
                  {saving ? t("saving3") : t("saveChanges")}
                </Button>
              )
            }
          >
            <div className="grid items-start gap-4 md:grid-cols-2">
              <FormField label={t("displayName")} htmlFor="profile-name">
                <Input
                  id="profile-name"
                  data-guidance={
                    (!!onContinue &&
                      !name.trim() &&
                      (!!user.avatar_url || user.avatar_color != null)) ||
                    undefined
                  }
                  value={name}
                  disabled={saving}
                  onChange={(e) => setName(e.target.value)}
                  placeholder={t("howShouldWeCall")}
                />
              </FormField>
              <FormField
                label={t("email")}
                htmlFor="profile-email"
                description={
                  user?.pending_email
                    ? t("emailChangePending", { email: user.pending_email })
                    : t("changingEmailMayRequire")
                }
              >
                <Input
                  id="profile-email"
                  type="email"
                  value={email}
                  disabled={saving}
                  onChange={(e) => setEmail(e.target.value)}
                />
              </FormField>
            </div>
          </SectionCard>

          {section === "identity" && onContinue && (
            <Button
              disabled={saving || avatarUploading}
              onClick={async () => {
                if (await handleSaveProfile()) onContinue();
              }}
            >
              {saveLabel ?? t("saveChanges")}
            </Button>
          )}
        </>
      )}
      {section !== "identity" && (
        <AgentContextSettings
          user={user}
          beforeSave={onContinue && section !== "context" ? handleSaveProfile : undefined}
          onSaved={onContinue}
          saveLabel={saveLabel}
        />
      )}
    </div>
  );
}
