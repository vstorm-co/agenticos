"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { usePublicConfig } from "@/components/public-config/public-config-provider";
import { SecretRevealField } from "@/components/triggers/secret-reveal-field";
import {
  Button,
  Checkbox,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { getErrorMessage } from "@/lib/api-error";
import { DIALOG_COLUMN } from "@/lib/dialog-sizes";
import type { ApiKeyCreateInput, ApiKeyCreated, ApiKeyScopeCatalog } from "@/types/api-keys";
import type { Permission } from "@/types/permissions";

/** How long a new key lives. `never` is a choice, not a default. */
const EXPIRIES = { "30": 30, "90": 90, "365": 365, never: null } as const;
type Expiry = keyof typeof EXPIRIES;

const CUSTOM = "custom";

interface CreateApiKeyDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  catalog: ApiKeyScopeCatalog;
  onCreate: (input: ApiKeyCreateInput) => Promise<ApiKeyCreated>;
  busy: boolean;
}

function expiresAt(choice: Expiry): string | null {
  const days = EXPIRIES[choice];
  return days === null ? null : new Date(Date.now() + days * 86_400_000).toISOString();
}

/**
 * Issue an organization API key, then show it - once.
 *
 * A preset picks the scopes for the usual jobs; "Custom" opens the catalog,
 * which holds only what the caller has, because a key never reaches further
 * than its issuer. After creation the form is replaced by the key itself:
 * the server keeps only a hash, so closing this dialog is the last chance to
 * copy it.
 */
export function CreateApiKeyDialog({
  open,
  onOpenChange,
  catalog,
  onCreate,
  busy,
}: CreateApiKeyDialogProps) {
  const t = useTranslations("apiKeys");
  const tErrors = useTranslations("errors");
  // The API's own origin, not this console's: a key is sent straight to the
  // backend, and the console's `/api` is a proxy that only carries a session.
  const { apiUrl } = usePublicConfig();
  const firstPreset = catalog.presets[0]?.id ?? CUSTOM;
  const [name, setName] = useState("");
  const [preset, setPreset] = useState<string>(firstPreset);
  const [custom, setCustom] = useState<Permission[]>([]);
  const [expiry, setExpiry] = useState<Expiry>("90");
  const [created, setCreated] = useState<ApiKeyCreated | null>(null);

  // "Custom" matches no preset, so the ticked permissions are what is sent.
  const chosen = catalog.presets.find((choice) => choice.id === preset);
  const scopes = chosen ? chosen.scopes : custom;

  // Opened from outside only - there is no trigger in here - so the dialog only
  // ever asks to close, and closing forgets the key it showed.
  const close = () => {
    setName("");
    setPreset(firstPreset);
    setCustom([]);
    setExpiry("90");
    setCreated(null);
    onOpenChange(false);
  };

  const submit = async () => {
    try {
      setCreated(await onCreate({ name: name.trim(), scopes, expires_at: expiresAt(expiry) }));
    } catch (error) {
      toast.error(getErrorMessage(error, tErrors));
    }
  };

  const toggle = (scope: Permission, on: boolean) =>
    setCustom((current) => (on ? [...current, scope] : current.filter((s) => s !== scope)));

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent className={DIALOG_COLUMN}>
        <DialogHeader>
          <DialogTitle>{created ? t("createdTitle") : t("createTitle")}</DialogTitle>
          <DialogDescription>{created ? t("createdWhy") : t("createWhy")}</DialogDescription>
        </DialogHeader>
        {created ? (
          <div className="min-h-0 flex-1 space-y-4 overflow-y-auto">
            <SecretRevealField
              id="api-key-secret"
              secret={created.key}
              label={created.name}
              note={t("shownOnce")}
            />
            <div className="text-muted-foreground space-y-1 text-xs">
              <p>{t("useItLikeThis")}</p>
              {/* i18n-exempt: a command line, identical in every language */}
              <code className="bg-muted block rounded px-2 py-1.5 font-mono break-all">
                {`curl -H "Authorization: Bearer ${created.prefix}…" ${apiUrl}/api/v1/me/permissions`}
              </code>
            </div>
          </div>
        ) : (
          <div className="min-h-0 flex-1 space-y-4 overflow-y-auto">
            <div className="space-y-1.5">
              <Label htmlFor="api-key-name">{t("name")}</Label>
              <Input
                id="api-key-name"
                value={name}
                maxLength={100}
                placeholder={t("namePlaceholder")}
                onChange={(event) => setName(event.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="api-key-preset">{t("access")}</Label>
              <Select value={preset} onValueChange={setPreset}>
                <SelectTrigger id="api-key-preset">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {catalog.presets.map((choice) => (
                    <SelectItem key={choice.id} value={choice.id}>
                      {t(`preset.${choice.id}`)}
                    </SelectItem>
                  ))}
                  <SelectItem value={CUSTOM}>{t("preset.custom")}</SelectItem>
                </SelectContent>
              </Select>
              <p className="text-muted-foreground text-xs">{t("accessWhy")}</p>
            </div>
            {chosen === undefined ? (
              <fieldset className="grid gap-2 sm:grid-cols-2" aria-label={t("access")}>
                {catalog.scopes.map((scope) => (
                  <label key={scope} className="flex items-center gap-2 font-mono text-xs">
                    <Checkbox
                      checked={custom.includes(scope)}
                      onCheckedChange={(on) => toggle(scope, on === true)}
                    />
                    {scope}
                  </label>
                ))}
              </fieldset>
            ) : (
              <p className="text-muted-foreground font-mono text-xs">{scopes.join(", ")}</p>
            )}
            <div className="space-y-1.5">
              <Label htmlFor="api-key-expiry">{t("expires")}</Label>
              <Select value={expiry} onValueChange={(value) => setExpiry(value as Expiry)}>
                <SelectTrigger id="api-key-expiry">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {(Object.keys(EXPIRIES) as Expiry[]).map((choice) => (
                    <SelectItem key={choice} value={choice}>
                      {t(`expiry.${choice}`)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
        )}
        <DialogFooter>
          {created ? (
            <Button onClick={close}>{t("done")}</Button>
          ) : (
            <Button
              disabled={busy || name.trim() === "" || scopes.length === 0}
              onClick={() => void submit()}
            >
              {t("create")}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
