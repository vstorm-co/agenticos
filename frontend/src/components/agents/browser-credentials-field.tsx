"use client";

import { useTranslations } from "next-intl";
import { Button, Checkbox, Label } from "@/components/ui";
import { useBrowserCredentialChoices } from "@/hooks/use-browser-credentials";
import { BrowserCredentialMetadata } from "@/components/vault/browser-credential-metadata";
import { isBrowserSecretKind } from "@/components/vault/browser-secret-fields";

export function BrowserCredentialsField({
  value,
  onChange,
  disabled,
  idPrefix,
}: {
  value: unknown;
  onChange: (ids: string[]) => void;
  disabled?: boolean;
  idPrefix: string;
}) {
  const t = useTranslations("browserCredentials");
  const query = useBrowserCredentialChoices("secrets");
  const selected = [
    ...new Set(
      Array.isArray(value) ? value.filter((id): id is string => typeof id === "string") : [],
    ),
  ];
  const secrets = (query.data?.pages.flatMap((page) => page.items) ?? []).filter((secret) =>
    isBrowserSecretKind(secret.kind),
  );
  const rows = [...new Map(secrets.map((secret) => [secret.id, secret])).values()];
  const missing = selected.filter((id) => !rows.some((secret) => secret.id === id));
  return (
    <fieldset className="space-y-3 rounded-lg border p-3" disabled={disabled}>
      <legend className="px-1 text-sm font-medium">{t("bindingTitle")}</legend>
      <p className="text-muted-foreground text-xs">{t("bindingHelp")}</p>
      {query.isPending && <p role="status">{t("loadingChoices")}</p>}
      {query.error && (
        <div role="alert" className="space-y-2">
          <p>{t("choicesUnavailable")}</p>
          <Button variant="outline" onClick={() => void query.refetch()}>
            {t("checkAgain")}
          </Button>
        </div>
      )}
      <div className="max-h-72 space-y-3 overflow-y-auto">
        {[
          ...missing.map((id) => ({ id, name: t("selectedUnavailable", { id }), browser: null })),
          ...rows,
        ].map((secret) => {
          const checked = selected.includes(secret.id);
          return (
            <div key={secret.id} className="space-y-1">
              <div className="flex items-center gap-2">
                <Checkbox
                  id={`${idPrefix}-credential-${secret.id}`}
                  checked={checked}
                  disabled={disabled || (!checked && selected.length >= 50)}
                  onCheckedChange={(value) =>
                    onChange(
                      value === true
                        ? [...selected, secret.id]
                        : selected.filter((id) => id !== secret.id),
                    )
                  }
                />
                <Label
                  className="min-w-0 break-words"
                  htmlFor={`${idPrefix}-credential-${secret.id}`}
                >
                  {secret.name}
                </Label>
              </div>
              {secret.browser && (
                <div className="pl-6">
                  <BrowserCredentialMetadata metadata={secret.browser} />
                </div>
              )}
            </div>
          );
        })}
      </div>
      {!query.isPending && !query.error && rows.length === 0 && (
        <p className="text-muted-foreground text-xs">
          {t(query.hasNextPage ? "noLoadedCredentials" : "noCredentials")}
        </p>
      )}
      {query.hasNextPage && (
        <Button
          variant="outline"
          loading={query.isFetchingNextPage}
          onClick={() => void query.fetchNextPage()}
        >
          {t("loadMore")}
        </Button>
      )}
      <p className="text-muted-foreground text-xs">
        {t("selectionCount", { count: selected.length, max: 50 })}
      </p>
    </fieldset>
  );
}
