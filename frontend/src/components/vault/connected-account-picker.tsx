"use client";

import { useId, useState } from "react";
import { ChevronRight, Mail } from "lucide-react";
import { useTranslations } from "next-intl";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui";
import {
  INTEGRATION_PROVIDERS,
  type AccountOwner,
  type IntegrationProvider,
} from "@/hooks/use-connected-accounts";
import { DIALOG_FORM } from "@/lib/dialog-sizes";
import { ProviderIcon } from "./provider-icon";

/** Choose ownership once, then a provider, rather than duplicating every service. */
export function ConnectedAccountPicker({
  allowOrganization = false,
  initialOwner = "personal",
  onSelect,
  onClose,
}: {
  allowOrganization?: boolean;
  initialOwner?: AccountOwner;
  onSelect: (target: { owner: AccountOwner; provider: IntegrationProvider }) => void;
  onClose: () => void;
}) {
  const t = useTranslations("pages.vault.connectedAccounts");
  const id = useId();
  const [owner, setOwner] = useState<AccountOwner>(allowOrganization ? initialOwner : "personal");
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className={DIALOG_FORM}>
        <DialogHeader>
          <DialogTitle>{t("picker.title")}</DialogTitle>
          <DialogDescription>{t("picker.description")}</DialogDescription>
        </DialogHeader>
        {allowOrganization && (
          <fieldset className="bg-muted flex rounded-lg p-1">
            <legend className="sr-only">{t("accountOwner")}</legend>
            {(["personal", "organization"] as const).map((value) => (
              <label key={value} className="flex-1 cursor-pointer">
                <input
                  type="radio"
                  className="peer sr-only"
                  name={`${id}-owner`}
                  checked={owner === value}
                  onChange={() => setOwner(value)}
                />
                <span className="peer-checked:bg-background peer-focus-visible:ring-ring touch:min-h-11 flex items-center justify-center rounded-md px-3 py-2 text-center text-sm peer-checked:shadow-sm peer-focus-visible:ring-2">
                  {t(`picker.${value}`)}
                </span>
              </label>
            ))}
          </fieldset>
        )}
        <div className="grid gap-2 sm:grid-cols-2">
          {INTEGRATION_PROVIDERS.map((provider) => (
            <button
              type="button"
              key={provider}
              aria-label={t(`setup.provider.${provider}`)}
              onClick={() => onSelect({ owner, provider })}
              className="hover:bg-muted/50 focus-visible:ring-ring flex items-center gap-3 rounded-xl border p-4 text-left transition-colors outline-none focus-visible:ring-2"
            >
              {provider === "imap" ? (
                <Mail className="size-6 shrink-0" aria-hidden />
              ) : (
                <ProviderIcon provider={provider} brand={provider} className="size-6 shrink-0" />
              )}
              <span className="min-w-0 flex-1">
                <span className="block text-sm font-medium">{t(`setup.provider.${provider}`)}</span>
                <span className="text-muted-foreground mt-0.5 block text-xs">
                  {t(`picker.products.${provider}`)}
                </span>
              </span>
              <ChevronRight className="text-muted-foreground size-3.5 shrink-0" aria-hidden />
            </button>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  );
}
