"use client";
import { useRef, useState } from "react";
import { Camera, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { useTranslations } from "next-intl";
import { AvatarColorPicker, Button, Input } from "@/components/ui";
import { useOrganizations } from "@/hooks";
import { usePermissions } from "@/hooks/use-permissions";
import { useUnsavedChanges } from "@/hooks/use-unsaved-changes";
import { useChanged } from "@/hooks/use-changed";
import { avatarInitials, avatarPalette } from "@/lib/avatar-color";
import { getErrorMessage } from "@/lib/api-error";
import { cn, MAX_AVATAR_SIZE_BYTES } from "@/lib/utils";
import type { Organization } from "@/types";
import { Perm } from "@/types/permissions";
import styles from "./organization-profile-settings.module.css";
export function OrganizationProfileSettings({
  org,
  onContinue,
  saveLabel,
}: {
  org: Organization;
  onContinue?: () => void;
  saveLabel?: string;
}) {
  const t = useTranslations("pages.orgs");
  const tc = useTranslations("common");
  const tErrors = useTranslations("errors");
  const { patchOrg, uploadAvatar } = useOrganizations();
  const { can } = usePermissions();
  const canManage = can(Perm.membersManage);
  // Workspace profile state - name edits stay local until "Save" lands the
  // PATCH; avatar uploads are immediate (a separate POST endpoint).
  const [name, setName] = useState("");
  const [savingName, setSavingName] = useState(false);
  const [avatarUploading, setAvatarUploading] = useState(false);
  const avatarInputRef = useRef<HTMLInputElement>(null);

  // Re-seeded when the stored name moves - a save coming back, or another tab.
  // During render, so the old name is never shown in the field.
  if (useChanged(`${org?.id}|${org?.name}`) && org) setName(org.name);

  const handleSaveName = async () => {
    const trimmed = name.trim();
    if (!trimmed) return false;
    if (trimmed === org.name) return true;
    setSavingName(true);
    try {
      return (await patchOrg(org.id, { name: trimmed })) !== null;
    } finally {
      setSavingName(false);
    }
  };

  useUnsavedChanges(`org-profile:${org.id}`, {
    dirty: canManage && !onContinue && name.trim() !== org.name,
    save: name.trim() ? handleSaveName : undefined,
    discard: () => setName(org.name),
  });

  const handleColorChange = async (slot: number | null) => {
    if (slot === (org.avatar_color ?? null)) return;
    await patchOrg(org.id, { avatar_color: slot });
  };

  const handleAvatarUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    e.target.value = "";
    if (file.size > MAX_AVATAR_SIZE_BYTES) {
      toast.error(t("avatarTooLargeMaximum"));
      return;
    }
    setAvatarUploading(true);
    try {
      await uploadAvatar(org.id, file);
      toast.success(t("workspaceAvatarUpdated"));
    } catch (err) {
      toast.error(getErrorMessage(err, tErrors, t("failedUploadAvatar")));
    } finally {
      setAvatarUploading(false);
    }
  };

  const colors = canManage && (
    <div>
      <p className="text-muted-foreground mb-2 text-xs">{t("avatarColour")}</p>
      <AvatarColorPicker
        value={org.avatar_color}
        onChange={handleColorChange}
        className={onContinue ? "justify-center" : undefined}
      />
    </div>
  );

  const heading = (
    <div>
      <p className="text-muted-foreground font-mono text-xs tracking-wider uppercase">
        {t("workspaceProfile")}
      </p>
      <p className="text-muted-foreground mt-0.5 text-xs">{t("nameAvatarShownAcross")}</p>
    </div>
  );

  return (
    <section
      data-tour="org-profile"
      data-guided={!!onContinue}
      className={cn(
        "border-border bg-card @container flex flex-wrap items-start gap-5 rounded-xl border p-5 sm:p-6",
        onContinue && styles.guided,
      )}
    >
      <button
        type="button"
        onClick={() => avatarInputRef.current?.click()}
        disabled={!canManage || avatarUploading}
        className={cn(
          "group relative flex h-16 w-16 shrink-0 items-center justify-center overflow-hidden rounded-full disabled:cursor-default",
          org.avatar_url ? "bg-muted text-foreground" : avatarPalette(org.id, org.avatar_color).bg,
        )}
        title={canManage ? t("changeWorkspaceAvatar") : t("onlyOwnersAdminsCan")}
      >
        {org.avatar_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={`/api/orgs/${org.id}/avatar?v=${org.updated_at ?? ""}`}
            alt=""
            className="h-full w-full object-cover"
          />
        ) : (
          <span
            className={cn(avatarPalette(org.id, org.avatar_color).fg, "text-base font-semibold")}
          >
            {avatarInitials(org.name)}
          </span>
        )}
        {canManage && (
          <span className="absolute inset-0 flex items-center justify-center bg-black/45 opacity-0 transition-opacity group-hover:opacity-100">
            {avatarUploading ? (
              <Loader2 className="h-5 w-5 animate-spin text-white" />
            ) : (
              <Camera className="h-5 w-5 text-white" />
            )}
          </span>
        )}
      </button>
      <input
        ref={avatarInputRef}
        type="file"
        accept="image/jpeg,image/png,image/webp,image/gif"
        className="hidden"
        onChange={handleAvatarUpload}
      />

      <div
        className={cn(
          "min-w-0 flex-1 space-y-3",
          onContinue ? styles.details : "@max-sm:basis-full",
        )}
      >
        {!onContinue && heading}
        {canManage && (
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={avatarUploading}
            data-guidance={
              (!!onContinue && !org.avatar_url && org.avatar_color == null) || undefined
            }
            onClick={() => avatarInputRef.current?.click()}
          >
            <Camera size={14} aria-hidden />
            {t("changeWorkspaceAvatar")}
          </Button>
        )}
        {onContinue && colors}
        {onContinue && heading}
        <div className="flex flex-col items-stretch gap-2 sm:flex-row sm:flex-wrap sm:items-center">
          <Input
            aria-label={t("workspaceName")}
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            disabled={!canManage || savingName}
            className="min-w-0 flex-1"
            placeholder={t("workspaceName")}
            maxLength={255}
          />
          {!onContinue && canManage && name.trim() !== org.name && name.trim() !== "" && (
            <Button onClick={handleSaveName} disabled={savingName}>
              {savingName ? <Loader2 className="h-4 w-4 animate-spin" /> : tc("save")}
            </Button>
          )}
        </div>
        {!canManage && <p className="text-muted-foreground text-xs">{t("onlyOwnersAdminsCan")}</p>}
        {!onContinue && colors}
        {onContinue && (
          <Button
            data-continue
            disabled={savingName || avatarUploading || !name.trim()}
            onClick={async () => {
              if (await handleSaveName()) onContinue();
            }}
          >
            {saveLabel ?? tc("save")}
          </Button>
        )}
      </div>
    </section>
  );
}
