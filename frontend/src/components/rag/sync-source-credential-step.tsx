"use client";

import { ExternalLink, KeyRound } from "lucide-react";
import { useTranslations } from "next-intl";

import { Label } from "@/components/ui";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { usePermissions, useSecrets } from "@/hooks";
import { ROUTES } from "@/lib/constants";
import type { ConnectorInfo, SyncSourceCreate } from "@/lib/rag-api";
import { Perm } from "@/types/permissions";

/**
 * Which vault credential this source authenticates with.
 *
 * A step of its own because the credential is no longer part of the connector's
 * configuration. It used to be a `secret: true` field in the configure step - a
 * textarea for a service account JSON, two password inputs for an AWS pair -
 * pasted into a JSONB column and encrypted with one deployment-wide key, per
 * source, so one Drive credential feeding five collections was the same JSON
 * pasted five times and rotated in five places (#937).
 *
 * **No inline form.** `InlineSecret` exists for exactly this - adding a key
 * without leaving the page - and it takes `api_key` only, deliberately: an AWS
 * pair and a service-account JSON are multi-field forms with their own
 * validation, and its own docstring says the honest place for those is the
 * Vault. So this offers what the organization holds and a link to go and add
 * one, which is the same answer that component gives for the shapes it does not
 * handle.
 */
export function CredentialStep({
  connector,
  form,
  setForm,
  error,
}: {
  connector: ConnectorInfo;
  form: SyncSourceCreate;
  setForm: React.Dispatch<React.SetStateAction<SyncSourceCreate>>;
  /** What the server said about `secret_id`, if it refused one. */
  error?: string;
}) {
  const t = useTranslations("rag");
  const { secrets } = useSecrets();
  const { can } = usePermissions();

  if (connector.secret_kind === "none") {
    return (
      <div className="border-foreground/10 bg-foreground/[0.03] rounded-xl border p-5 text-center">
        <KeyRound className="text-foreground/45 mx-auto h-6 w-6" />
        <p className="text-foreground/70 mt-3 text-sm">
          {t("credentialNoneNeeded", { name: connector.name })}
        </p>
      </div>
    );
  }

  // Before the picker, not as an empty one: a member who cannot see the
  // organization's credentials is not looking at a list that happens to be
  // empty, and saying so is the difference between "ask somebody" and "add one".
  if (!can(Perm.secretsView)) {
    return <p className="text-muted-foreground text-sm">{t("credentialNeedsPermission")}</p>;
  }

  const usable = secrets.filter((secret) => secret.kind === connector.secret_kind);
  const chosen = form.secret_id ?? "";

  return (
    <div className="space-y-4">
      <p className="text-foreground/65 text-sm">{t("credentialIntro", { name: connector.name })}</p>

      <div className="space-y-1.5">
        <Label
          htmlFor="sync-credential"
          className="text-foreground/80 text-xs font-medium tracking-wider uppercase"
        >
          {t("credentialLabel")}
          <span className="text-destructive ml-0.5">*</span>
        </Label>
        <Select
          value={chosen}
          onValueChange={(value) => setForm((f) => ({ ...f, secret_id: value }))}
          disabled={usable.length === 0}
        >
          <SelectTrigger
            id="sync-credential"
            {...(error === undefined
              ? {}
              : { "aria-invalid": true, "aria-describedby": "sync-credential-error" })}
          >
            <SelectValue placeholder={t("credentialPlaceholder")} />
          </SelectTrigger>
          <SelectContent>
            {usable.map((secret) => (
              <SelectItem key={secret.id} value={secret.id} textValue={secret.name}>
                <span className="flex items-center gap-2">
                  <KeyRound className="text-foreground/45 h-3.5 w-3.5" />
                  <span>{secret.name}</span>
                  <span className="text-foreground/45 font-mono text-xs">··{secret.hint}</span>
                </span>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {error !== undefined && (
          <p id="sync-credential-error" className="text-destructive text-xs">
            {error}
          </p>
        )}
      </div>

      {/* A picker with nothing in it and no way to fill it is a dead end, which
          is the state this whole step replaced - the credential was a textarea
          and every source got its own copy. Opened in a new tab so the
          half-filled wizard behind it survives. */}
      <p className="text-foreground/55 text-sm">
        {usable.length === 0
          ? t("credentialNoneStored", { name: connector.name })
          : t("credentialAddAnother")}{" "}
        <a
          href={ROUTES.VAULT}
          target="_blank"
          rel="noreferrer"
          className="text-foreground inline-flex items-center gap-1 underline underline-offset-2"
        >
          {t("credentialOpenVault")}
          <ExternalLink className="h-3 w-3" />
        </a>
      </p>
    </div>
  );
}
