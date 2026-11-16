"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { useConnectedAccounts, type IntegrationProvider } from "@/hooks/use-connected-accounts";
import { ErrorState } from "@/components/states";
import {
  Checkbox,
  FormField,
  Input,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { getErrorMessage } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";

/** Account identifiers are selected from the signed-in member's visible accounts. */
export function IntegrationAccountFields({
  productId,
  provider,
  config,
  onChange,
  disabled,
  configErrors = {},
}: {
  productId: string;
  provider: IntegrationProvider;
  config: Record<string, unknown>;
  onChange: (config: Record<string, unknown>) => void;
  disabled?: boolean;
  configErrors?: Readonly<Record<string, string>>;
}) {
  const t = useTranslations("pages.vault.connectedAccounts");
  const errors = useTranslations("errors");
  const owner = config.account === "organization" ? "organization" : "personal";
  const { accounts, isLoading, error } = useConnectedAccounts(owner, {
    provider,
    enabled: !disabled,
  });
  const prefix = `integration-${productId}`;
  return (
    <div className="space-y-4">
      <FormField label={t("accountOwner")} htmlFor={`${prefix}-owner`} error={configErrors.account}>
        <Select
          value={owner}
          disabled={disabled}
          onValueChange={(account) =>
            onChange({
              ...config,
              account,
              connection_id: null,
              connection_ids: [],
              account_name: "",
            })
          }
        >
          <SelectTrigger id={`${prefix}-owner`}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="personal">{t("personalTitle")}</SelectItem>
            <SelectItem value="organization">{t("organizationTitle")}</SelectItem>
          </SelectContent>
        </Select>
      </FormField>
      {error && <ErrorState description={getErrorMessage(error, errors)} />}
      {owner === "organization" ? (
        <fieldset className="space-y-2" disabled={disabled || isLoading}>
          <legend className="text-sm font-medium">{t("chooseAccounts")}</legend>
          {accounts.map((account) => {
            const selected = [
              ...new Set([
                ...(typeof config.connection_id === "string" ? [config.connection_id] : []),
                ...(Array.isArray(config.connection_ids)
                  ? config.connection_ids.filter((id): id is string => typeof id === "string")
                  : []),
              ]),
            ];
            const label = account.label ? `${account.label} — ${account.email}` : account.email;
            return (
              <label key={account.id} className="flex items-center gap-2 text-sm">
                <Checkbox
                  aria-label={label}
                  checked={selected.includes(account.id)}
                  onCheckedChange={(checked) =>
                    onChange({
                      ...config,
                      connection_id: null,
                      connection_ids: checked
                        ? [...selected, account.id]
                        : selected.filter((id) => id !== account.id),
                    })
                  }
                />
                {label}
              </label>
            );
          })}
          {(configErrors.connection_ids || configErrors.connection_id) && (
            <p role="alert" className="text-destructive text-xs">
              {configErrors.connection_ids || configErrors.connection_id}
            </p>
          )}
          <p className="text-muted-foreground text-xs">{t("multipleAccountsHint")}</p>
        </fieldset>
      ) : (
        <FormField
          label={t("accountNameLabel")}
          htmlFor={`${prefix}-name`}
          description={t("accountNameHint")}
          error={configErrors.account_name}
        >
          <Input
            id={`${prefix}-name`}
            list={`${prefix}-names`}
            value={typeof config.account_name === "string" ? config.account_name : ""}
            disabled={disabled}
            maxLength={320}
            onChange={(event) => onChange({ ...config, account_name: event.target.value })}
          />
          <datalist id={`${prefix}-names`}>
            {accounts.map((account) => (
              <option key={account.id} value={account.name || account.email}>
                {account.label ? `${account.label} — ${account.email}` : account.email}
              </option>
            ))}
          </datalist>
        </FormField>
      )}
      <Link
        href={ROUTES.VAULT}
        className="text-muted-foreground text-xs underline underline-offset-4"
      >
        {t("manageAccounts")}
      </Link>
    </div>
  );
}
