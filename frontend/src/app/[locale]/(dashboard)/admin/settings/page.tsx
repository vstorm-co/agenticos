"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2, Save } from "lucide-react";
import { useTranslations } from "next-intl";

import { BrandingImageField } from "@/components/admin/branding-image-field";
import { DomainListField } from "@/components/admin/domain-list-field";
import { ErrorState, LoadingState } from "@/components/states";
import { Button, FormField, Input, ListCard, Switch, Textarea } from "@/components/ui";
import {
  useDeploymentSettings,
  type DeploymentSettingsPatch,
} from "@/hooks/use-deployment-settings";
import { getErrorMessage } from "@/lib/api-error";
import { BUILT_IN_BRANDING, type NoticeLevel, type SignupMode } from "@/lib/branding";

const SIGNUP_MODES: readonly SignupMode[] = ["open", "invite_only", "closed"];
const NOTICE_LEVELS: readonly NoticeLevel[] = ["info", "warning", "critical"];

/**
 * The deployment's own settings - what it is called, what it looks like, who may
 * join it, and whether it is open.
 *
 * One page for all of it rather than four, because they are one row and one save.
 * The sections below are the reader's grouping, not four requests.
 *
 * **An empty input clears an override.** That is the whole editing model here: a
 * field left blank falls back to what this build ships with, so the placeholders
 * show the built-in rather than pretending the field is empty. It is also why the
 * save sends `null` and not `""` - the backend treats a blank as "give me the
 * default back", and storing `""` would render a sign-in page with no name on it.
 *
 * The draft is the server's row with this session's edits laid over it, and the
 * save sends only the edits. Copying the row into state on arrival would make every
 * save a full write of every field, so renaming the deployment would also resend -
 * and quietly re-assert - an announcement somebody else had changed meanwhile.
 */
export default function DeploymentSettingsPage() {
  const t = useTranslations("pages.admin");
  const tc = useTranslations("common");
  const tErrors = useTranslations("errors");
  const router = useRouter();
  const { settings, isLoading, error, refetch, save, uploadImage, clearImage } =
    useDeploymentSettings();

  // Only the fields this administrator has touched. The draft is derived from them
  // over the server's answer rather than copied into state when it arrives, which
  // is what makes the PATCH honest: what is sent is what was edited, so saving the
  // name cannot silently rewrite an announcement somebody else changed meanwhile.
  // It is also why an upload - which answers with the whole row - immediately shows
  // its new mark without anything here re-seeding.
  const [edits, setEdits] = useState<DeploymentSettingsPatch>({});

  if (isLoading) return <LoadingState variant="stats" rows={4} />;
  if (error || !settings) {
    return (
      <ErrorState
        title={t("settingsUnreadable")}
        description={getErrorMessage(error, tErrors, t("settingsUnreadableBody"))}
        cta={{ label: tc("retry"), onClick: () => void refetch() }}
      />
    );
  }

  const draft: DeploymentSettingsPatch = {
    app_name: settings.app_name,
    tagline: settings.tagline,
    description: settings.description,
    footer_text: settings.footer_text,
    terms_url: settings.terms_url,
    privacy_url: settings.privacy_url,
    signup_mode: settings.signup_mode,
    allowed_email_domains: settings.allowed_email_domains,
    announcement: settings.announcement,
    announcement_level: settings.announcement_level,
    maintenance_mode: settings.maintenance_mode,
    maintenance_message: settings.maintenance_message,
    max_organizations_per_user: settings.max_organizations_per_user,
    max_agents_per_organization: settings.max_agents_per_organization,
    notify_impersonated_users: settings.notify_impersonated_users,
    ...edits,
  };

  const set = <K extends keyof DeploymentSettingsPatch>(
    key: K,
    value: DeploymentSettingsPatch[K],
  ) => setEdits({ ...edits, [key]: value });

  /**
   * A ceiling's value, sent as `null` when emptied - which is how "no limit" is
   * said. Empty rather than `0`, because zero is not a limit anybody means: it
   * would leave an account that cannot own the personal organization sign-up
   * creates for it, and the schema refuses it.
   */
  const ceiling = (key: "max_organizations_per_user" | "max_agents_per_organization") => ({
    type: "number",
    min: 1,
    value: draft[key] === null || draft[key] === undefined ? "" : String(draft[key]),
    onChange: (event: { target: { value: string } }) =>
      set(key, event.target.value === "" ? null : Number(event.target.value)),
    disabled: save.isPending,
  });

  /** A text input's value, sent as `null` when emptied so the built-in returns. */
  const text = (key: keyof DeploymentSettingsPatch) => ({
    value: (draft[key] as string | null) ?? "",
    onChange: (event: { target: { value: string } }) =>
      set(key, (event.target.value || null) as DeploymentSettingsPatch[typeof key]),
    disabled: save.isPending,
  });

  const submit = () => {
    // `router.refresh()` because every surface that draws the name reads it from a
    // context the server resolved above `[locale]`: without it the form would show
    // a saved name the sidebar beside it still disagrees with.
    save.mutate(edits, {
      onSuccess: () => {
        setEdits({});
        router.refresh();
      },
    });
  };

  const busy = uploadImage.isPending || clearImage.isPending;

  return (
    <div className="space-y-6">
      <ListCard title={t("brandingIdentity")} counted={t("brandingIdentityHint")}>
        <div className="space-y-5">
          <FormField
            label={t("brandingName")}
            htmlFor="app-name"
            description={t("brandingNameHint")}
          >
            <Input
              id="app-name"
              // The built-in itself, so "empty means the default" is visible rather
              // than described. Not copy: it is the product's own name, read from
              // the one constant that holds it.
              placeholder={BUILT_IN_BRANDING.appName}
              maxLength={64}
              {...text("app_name")}
            />
          </FormField>

          <FormField
            label={t("brandingTagline")}
            htmlFor="tagline"
            description={t("brandingTaglineHint")}
          >
            <Input
              id="tagline"
              placeholder={BUILT_IN_BRANDING.tagline}
              maxLength={160}
              {...text("tagline")}
            />
          </FormField>

          <FormField
            label={t("brandingDescription")}
            htmlFor="description"
            description={t("brandingDescriptionHint")}
          >
            <Textarea
              id="description"
              placeholder={BUILT_IN_BRANDING.description}
              rows={2}
              maxLength={320}
              {...text("description")}
            />
          </FormField>

          <BrandingImageField
            kind="logo"
            version={settings.logo_version}
            busy={busy}
            onUpload={(file) => uploadImage.mutate({ kind: "logo", file })}
            onClear={() => clearImage.mutate("logo")}
          />
          <BrandingImageField
            kind="favicon"
            version={settings.favicon_version}
            busy={busy}
            onUpload={(file) => uploadImage.mutate({ kind: "favicon", file })}
            onClear={() => clearImage.mutate("favicon")}
          />
        </div>
      </ListCard>

      <ListCard title={t("brandingLegal")} counted={t("brandingLegalHint")}>
        <div className="space-y-5">
          <FormField label={t("brandingFooter")} htmlFor="footer-text">
            <Input id="footer-text" maxLength={280} {...text("footer_text")} />
          </FormField>
          <FormField
            label={t("brandingTerms")}
            htmlFor="terms-url"
            description={t("brandingLinkHint")}
          >
            <Input
              id="terms-url"
              type="url"
              placeholder="https://example.com/terms"
              {...text("terms_url")}
            />
          </FormField>
          <FormField label={t("brandingPrivacy")} htmlFor="privacy-url">
            <Input
              id="privacy-url"
              type="url"
              placeholder="https://example.com/privacy"
              {...text("privacy_url")}
            />
          </FormField>
        </div>
      </ListCard>

      <ListCard title={t("accessSignup")} counted={t("accessSignupHint")}>
        <div className="space-y-5">
          <FormField
            label={t("accessMode")}
            htmlFor="signup-mode"
            description={t(`accessMode_${draft.signup_mode ?? "open"}`)}
          >
            <select
              id="signup-mode"
              value={draft.signup_mode ?? "open"}
              onChange={(event) => set("signup_mode", event.target.value as SignupMode)}
              disabled={save.isPending}
              className="border-border bg-background text-foreground h-10 w-full rounded-lg border px-3 text-sm"
            >
              {SIGNUP_MODES.map((mode) => (
                <option key={mode} value={mode}>
                  {t(`accessModeLabel_${mode}`)}
                </option>
              ))}
            </select>
          </FormField>

          <FormField
            label={t("accessDomains")}
            htmlFor="allowed-domains"
            description={t("accessDomainsHint")}
          >
            <DomainListField
              domains={draft.allowed_email_domains ?? []}
              onChange={(next) => set("allowed_email_domains", next)}
              disabled={save.isPending}
            />
          </FormField>
        </div>
      </ListCard>

      {/* Beside sign-up rather than under branding: a ceiling is about who may
          use this deployment and how much of it, which is the question the card
          above answers for the door. */}
      <ListCard title={t("limitsTitle")} counted={t("limitsHint")}>
        <div className="space-y-5">
          <FormField
            label={t("limitsOrganizations")}
            htmlFor="max-organizations"
            description={t("limitsOrganizationsHint")}
          >
            <Input
              id="max-organizations"
              placeholder={t("limitsUnlimited")}
              {...ceiling("max_organizations_per_user")}
            />
          </FormField>
          <FormField
            label={t("limitsAgents")}
            htmlFor="max-agents"
            description={t("limitsAgentsHint")}
          >
            <Input
              id="max-agents"
              placeholder={t("limitsUnlimited")}
              {...ceiling("max_agents_per_organization")}
            />
          </FormField>
        </div>
      </ListCard>

      <ListCard title={t("adminAccessTitle")} counted={t("adminAccessHint")}>
        <div className="border-border flex items-start justify-between gap-4 rounded-xl border p-4">
          <div className="min-w-0">
            <p className="text-foreground text-sm font-medium">{t("impersonationNoticeToggle")}</p>
            <p className="text-muted-foreground mt-0.5 text-xs">
              {t("impersonationNoticeToggleHint")}
            </p>
          </div>
          <Switch
            checked={draft.notify_impersonated_users ?? false}
            onCheckedChange={(checked) => set("notify_impersonated_users", checked)}
            disabled={save.isPending}
            aria-label={t("impersonationNoticeToggle")}
          />
        </div>
      </ListCard>

      <ListCard title={t("noticesTitle")} counted={t("noticesHint")}>
        <div className="space-y-5">
          <FormField
            label={t("noticeAnnouncement")}
            htmlFor="announcement"
            description={t("noticeAnnouncementHint")}
          >
            <Textarea id="announcement" rows={2} maxLength={500} {...text("announcement")} />
          </FormField>

          <FormField label={t("noticeLevel")} htmlFor="announcement-level">
            <select
              id="announcement-level"
              value={draft.announcement_level ?? "info"}
              onChange={(event) => set("announcement_level", event.target.value as NoticeLevel)}
              disabled={save.isPending}
              className="border-border bg-background text-foreground h-10 w-full rounded-lg border px-3 text-sm"
            >
              {NOTICE_LEVELS.map((level) => (
                <option key={level} value={level}>
                  {t(`noticeLevelLabel_${level}`)}
                </option>
              ))}
            </select>
          </FormField>

          <div className="border-border flex items-start justify-between gap-4 rounded-xl border p-4">
            <div className="min-w-0">
              <p className="text-foreground text-sm font-medium">{t("maintenanceToggle")}</p>
              <p className="text-muted-foreground mt-0.5 text-xs">{t("maintenanceToggleHint")}</p>
            </div>
            <Switch
              checked={draft.maintenance_mode ?? false}
              onCheckedChange={(checked) => set("maintenance_mode", checked)}
              disabled={save.isPending}
              aria-label={t("maintenanceToggle")}
            />
          </div>

          <FormField
            label={t("maintenanceMessage")}
            htmlFor="maintenance-message"
            description={t("maintenanceMessageHint")}
          >
            <Textarea
              id="maintenance-message"
              rows={2}
              maxLength={500}
              {...text("maintenance_message")}
            />
          </FormField>
        </div>
      </ListCard>

      <div className="flex justify-end">
        <Button onClick={submit} disabled={save.isPending || !Object.keys(edits).length}>
          {save.isPending ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Save className="h-4 w-4" />
          )}
          {tc("save")}
        </Button>
      </div>
    </div>
  );
}
