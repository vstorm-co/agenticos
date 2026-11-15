"use client";

import Image from "next/image";
import { useRef, useState, type ReactNode } from "react";
import { Camera } from "lucide-react";
import { toast } from "sonner";

import { ApiError, getErrorMessage } from "@/lib/api-error";
import { AvatarColorPicker, Button, FormField, Input, MoreOptions } from "@/components/ui";
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
  secondaryAction,
  section = "all",
}: {
  onContinue?: () => void;
  saveLabel?: string;
  secondaryAction?: ReactNode;
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
  const [colorSaving, setColorSaving] = useState(false);
  const [contextSaving, setContextSaving] = useState(false);
  const identityBusy = saving || avatarUploading || colorSaving;
  const busy = identityBusy || contextSaving;
  const avatarInputRef = useRef<HTMLInputElement>(null);

  // Re-seeded when the stored profile moves - a save coming back, or another
  // tab. During render, so a stale name is never shown in the field.
  if (useChanged(`${user?.id}|${user?.email}|${user?.full_name}`)) {
    setName(user?.full_name ?? "");
    setEmail(user?.email ?? "");
  }

  const handleSaveProfile = async () => {
    if (!user || identityBusy) return false;
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
    if (!file || busy) return;
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
    if (!user || busy || slot === (user.avatar_color ?? null)) return;
    setColorSaving(true);
    try {
      const updated = await apiClient.patch<User>("/users/me", { avatar_color: slot });
      setUser(updated);
    } catch (err) {
      toast.error(
        err instanceof ApiError ? getErrorMessage(err, tErrors) : t("failedUpdateProfile"),
      );
    } finally {
      setColorSaving(false);
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
        <SectionCard
          title={t("personalInfo")}
          description={t("visibleTeammatesSharedOrganizations")}
        >
          <form
            aria-label={t("personalInfo")}
            onSubmit={async (event) => {
              event.preventDefault();
              if (busy) return;
              if (await handleSaveProfile()) onContinue?.();
            }}
          >
            <fieldset disabled={busy} className="min-w-0 space-y-5">
              <legend className="sr-only">{t("personalInfo")}</legend>
              <div className={cn("space-y-4", onContinue && styles.avatarEditor)}>
                <div
                  className={cn("flex items-center gap-4", onContinue && styles.portraitControls)}
                >
                  <button
                    type="button"
                    onClick={() => avatarInputRef.current?.click()}
                    disabled={busy}
                    aria-label={user.avatar_url ? t("replaceAvatar3") : t("uploadAvatar3")}
                    className={cn(
                      "border-border hover:bg-accent group relative flex size-16 shrink-0 items-center justify-center overflow-hidden rounded-full border transition-colors",
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
                      <AvatarFace seed={user.id} colorSlot={user.avatar_color} />
                    )}
                    <span className="absolute inset-0 flex items-center justify-center bg-black/50 opacity-0 transition-opacity group-hover:opacity-100">
                      <Camera className="size-5 text-white" aria-hidden />
                    </span>
                  </button>
                  <input
                    ref={avatarInputRef}
                    type="file"
                    accept="image/jpeg,image/png,image/webp,image/gif"
                    onChange={handleAvatarUpload}
                    disabled={busy}
                    className="hidden"
                  />
                  <div className="min-w-0">
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => avatarInputRef.current?.click()}
                      disabled={busy}
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
                    <p className="text-muted-foreground mt-1 text-xs">
                      {t("squareImagesLookBest")}
                    </p>
                  </div>
                </div>
                <MoreOptions label={t("avatarColour")}>
                  <p className="text-muted-foreground text-xs">{t("avatarColourHint")}</p>
                  <AvatarColorPicker
                    value={user.avatar_color ?? null}
                    disabled={busy}
                    onChange={handleColorChange}
                    className={onContinue ? "justify-center" : undefined}
                  />
                </MoreOptions>
              </div>
              <div className="grid items-start gap-4 md:grid-cols-2">
                <FormField label={t("displayName")} htmlFor="profile-name">
                  <Input
                    id="profile-name"
                    name="full_name"
                    autoComplete="name"
                    value={name}
                    onChange={(event) => setName(event.target.value)}
                    placeholder={t("howShouldWeCall")}
                    data-guidance={
                      (!!onContinue &&
                        !name.trim() &&
                        (!!user.avatar_url || user.avatar_color != null)) ||
                      undefined
                    }
                  />
                </FormField>
                <FormField
                  label={t("email")}
                  htmlFor="profile-email"
                  description={
                    user.pending_email
                      ? t("emailChangePending", { email: user.pending_email })
                      : t("changingEmailMayRequire")
                  }
                >
                  <Input
                    id="profile-email"
                    name="email"
                    type="email"
                    autoComplete="email"
                    required
                    value={email}
                    onChange={(event) => setEmail(event.target.value)}
                  />
                </FormField>
              </div>
              <div
                data-profile-actions
                className="flex flex-wrap items-center justify-end gap-3 border-t pt-4"
              >
                <Button
                  type="submit"
                  loading={saving}
                  disabled={busy || (!onContinue && !profileChanged)}
                  className="w-full sm:w-auto"
                >
                  {saveLabel ?? t("saveChanges")}
                </Button>
                {secondaryAction}
              </div>
            </fieldset>
          </form>
        </SectionCard>
      )}
      {section !== "identity" && (
        <AgentContextSettings
          user={user}
          disabled={identityBusy}
          onSavingChange={setContextSaving}
          beforeSave={onContinue && section !== "context" ? handleSaveProfile : undefined}
          onSaved={onContinue}
          saveLabel={saveLabel}
          secondaryAction={secondaryAction}
        />
      )}
    </div>
  );
}
