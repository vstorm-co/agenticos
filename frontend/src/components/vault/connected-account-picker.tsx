"use client";

import { useId, useState } from "react";
import { ChevronRight, Mail } from "lucide-react";
import { useTranslations } from "next-intl";
import {
  Button,
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
import { DIALOG_BODY, DIALOG_COLUMN, DIALOG_FORM } from "@/lib/dialog-sizes";
import type { BrandName } from "@/components/icons/brand-icon";
import type { AccountSetupTarget } from "./connected-account-setup";
import { ProviderIcon } from "./provider-icon";

const PRODUCT_CHOICES: Readonly<
  Partial<Record<IntegrationProvider, readonly { id: string; brand: BrandName }[]>>
> = {
  google: [
    { id: "gmail", brand: "gmail" },
    { id: "google_calendar", brand: "googlecalendar" },
    { id: "google_drive", brand: "gdrive" },
    { id: "google_docs", brand: "gdocs" },
    { id: "google_sheets", brand: "gsheets" },
    { id: "google_slides", brand: "gslides" },
  ],
  microsoft: [
    { id: "outlook_mail", brand: "outlook" },
    { id: "outlook_calendar", brand: "outlookcalendar" },
    { id: "microsoft_files", brand: "onedrive" },
    { id: "excel", brand: "excel" },
    { id: "word", brand: "word" },
    { id: "teams", brand: "microsoftteams" },
  ],
};

/** Start with the service people recognize, then request its provider's consent. */
export function ConnectedAccountPicker({
  allowOrganization = false,
  initialOwner = "personal",
  onSelect,
  onClose,
}: {
  allowOrganization?: boolean;
  initialOwner?: AccountOwner;
  onSelect: (target: Pick<AccountSetupTarget, "owner" | "provider" | "products">) => void;
  onClose: () => void;
}) {
  const t = useTranslations("pages.vault.connectedAccounts");
  const productName = useTranslations("capabilityGuide");
  const id = useId();
  const [owner, setOwner] = useState<AccountOwner>(allowOrganization ? initialOwner : "personal");
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className={`${DIALOG_FORM} ${DIALOG_COLUMN}`}>
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
                <span className="peer-checked:bg-background peer-focus-visible:outline-foreground/60 touch:min-h-11 flex items-center justify-center rounded-xl px-3 py-2 text-center text-sm peer-checked:shadow-sm peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2">
                  {t(`picker.${value}`)}
                </span>
              </label>
            ))}
          </fieldset>
        )}
        <div className={DIALOG_BODY}>
          <div className="grid gap-2 sm:grid-cols-2">
            {INTEGRATION_PROVIDERS.flatMap((provider) =>
              (PRODUCT_CHOICES[provider] ?? [{ id: null, brand: provider }]).map((product) => {
                const name = product.id
                  ? productName(`${product.id}.name`)
                  : t(`setup.provider.${provider}`);
                return (
                  <Button
                    type="button"
                    variant="outline"
                    key={product.id ?? provider}
                    aria-labelledby={`${id}-${product.id ?? provider}-name`}
                    aria-describedby={`${id}-${product.id ?? provider}-hint`}
                    onClick={() =>
                      onSelect({
                        owner,
                        provider,
                        ...(product.id ? { products: [product.id] } : {}),
                      })
                    }
                    className="h-auto min-h-14 justify-start gap-3 p-3 text-left whitespace-normal"
                  >
                    {provider === "imap" ? (
                      <Mail className="size-6 shrink-0" aria-hidden />
                    ) : (
                      <ProviderIcon
                        provider={provider}
                        brand={product.brand}
                        className="size-6 shrink-0"
                      />
                    )}
                    <span className="min-w-0 flex-1">
                      <span
                        id={`${id}-${product.id ?? provider}-name`}
                        className="block text-sm font-medium"
                      >
                        {name}
                      </span>
                      <span
                        id={`${id}-${product.id ?? provider}-hint`}
                        className="text-muted-foreground mt-0.5 block text-xs"
                      >
                        {product.id
                          ? t(`setup.provider.${provider}`)
                          : t(`picker.products.${provider}`)}
                      </span>
                    </span>
                    <ChevronRight className="text-muted-foreground size-3.5 shrink-0" aria-hidden />
                  </Button>
                );
              }),
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
