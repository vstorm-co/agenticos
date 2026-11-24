"use client";

import { useTranslations } from "next-intl";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { BROWSER_PROFILE_FIELDS } from "@/types/browser-credentials";

export { isBrowserSecretKind } from "@/types/secrets";

/** Check the written consent boundary; the server also verifies the destination. */
export function isExactBrowserOrigin(value: string): boolean {
  if (!/^https:\/\/[^/?#\\\s]+\/?$/i.test(value)) return false;
  try {
    const url = new URL(value);
    return (
      url.protocol === "https:" &&
      !!url.hostname &&
      !url.username &&
      !url.password &&
      url.pathname === "/" &&
      !url.search &&
      !url.hash &&
      !url.hostname.includes("*")
    );
  } catch {
    return false;
  }
}

function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

export function isBrowserSecretComplete(
  kind: "browser_login" | "browser_profile",
  value: Record<string, unknown>,
): boolean {
  const origins = value.allowed_origins;
  if (
    !Array.isArray(origins) ||
    origins.length < 1 ||
    origins.length > 20 ||
    !origins.every((origin) => typeof origin === "string" && isExactBrowserOrigin(origin))
  )
    return false;
  if (kind === "browser_profile") {
    const entries = Object.entries(record(value.fields));
    return (
      entries.length > 0 &&
      entries.length <= BROWSER_PROFILE_FIELDS.length &&
      entries.every(
        ([field, entry]) =>
          BROWSER_PROFILE_FIELDS.some((known) => known === field) &&
          typeof entry === "string" &&
          entry.trim().length > 0 &&
          entry.length <= 1024,
      )
    );
  }
  // Browser passwords have no public hint or generic eight-character minimum.
  if (
    typeof value.username !== "string" ||
    !value.username.trim() ||
    value.username.length > 1024 ||
    typeof value.password !== "string" ||
    !value.password.length ||
    value.password.length > 4096
  )
    return false;
  if (value.totp == null) return true;
  const totp = record(value.totp);
  return (
    typeof totp.seed === "string" &&
    totp.seed.trim().length >= 16 &&
    totp.seed.trim().length <= 208 &&
    /^[A-Z2-7]+=*$/i.test(totp.seed.trim()) &&
    ["SHA1", "SHA256", "SHA512"].includes(String(totp.algorithm)) &&
    [6, 8].includes(Number(totp.digits)) &&
    [30, 60].includes(Number(totp.period_seconds))
  );
}

export function BrowserSecretFields({
  kind,
  value,
  onChange,
  disabled,
  idPrefix,
  errors = {},
}: {
  kind: "browser_login" | "browser_profile";
  value: Record<string, unknown>;
  onChange: (value: Record<string, unknown>) => void;
  disabled?: boolean;
  idPrefix: string;
  errors?: Readonly<Record<string, string>>;
}) {
  const t = useTranslations("browserCredentials");
  const origins = Array.isArray(value.allowed_origins) ? value.allowed_origins : [];
  const fields = record(value.fields);
  const totp = record(value.totp);
  const withTotp = value.totp != null;
  const id = (field: string) => `${idPrefix}-${field.replaceAll(".", "-")}`;
  const errorProps = (field: string) =>
    errors[field] === undefined
      ? {}
      : {
          "aria-invalid": true as const,
          "aria-describedby": `${id(field)}-error`,
        };
  const failure = (field: string) =>
    errors[field] === undefined ? null : (
      <p id={`${id(field)}-error`} className="text-destructive text-xs">
        {errors[field]}
      </p>
    );
  function set(field: string, next: unknown) {
    onChange({ ...value, [field]: next });
  }
  function setTotp(field: string, next: unknown) {
    set("totp", { ...totp, [field]: next });
  }
  return (
    <div className="space-y-4">
      <p className="text-muted-foreground text-sm">{t("formDescription")}</p>
      <div className="space-y-2">
        <Label htmlFor={id("allowed_origins")}>{t("origins")}</Label>
        <Textarea
          id={id("allowed_origins")}
          value={origins.join("\n")}
          onChange={(event) => set("allowed_origins", event.target.value.split("\n"))}
          disabled={disabled}
          autoComplete="off"
          spellCheck={false}
          placeholder="https://accounts.example.com"
          {...errorProps("allowed_origins")}
        />
        <p className="text-muted-foreground text-xs">{t("originsHelp")}</p>
        {failure("allowed_origins")}
      </div>
      {kind === "browser_login" ? (
        <>
          {(["username", "password"] as const).map((field) => (
            <div className="space-y-2" key={field}>
              <Label htmlFor={id(field)}>{t(field)}</Label>
              <Input
                id={id(field)}
                type="password"
                autoComplete="new-password"
                value={typeof value[field] === "string" ? value[field] : ""}
                onChange={(event) => set(field, event.target.value)}
                maxLength={field === "password" ? 4096 : 1024}
                disabled={disabled}
                {...errorProps(field)}
              />
              {failure(field)}
            </div>
          ))}
          <div className="flex items-center gap-2">
            <Checkbox
              id={id("with-totp")}
              checked={withTotp}
              disabled={disabled}
              onCheckedChange={(checked) => {
                if (checked === true)
                  set("totp", { seed: "", algorithm: "SHA1", digits: 6, period_seconds: 30 });
                else {
                  const next = { ...value };
                  delete next.totp;
                  onChange(next);
                }
              }}
            />
            <Label htmlFor={id("with-totp")}>{t("includeTotp")}</Label>
          </div>
          {withTotp && (
            <div className="space-y-4 rounded-lg border p-3">
              <div className="space-y-2">
                <Label htmlFor={id("totp.seed")}>{t("totpSeed")}</Label>
                <Input
                  id={id("totp.seed")}
                  type="password"
                  autoComplete="new-password"
                  value={typeof totp.seed === "string" ? totp.seed : ""}
                  onChange={(event) => setTotp("seed", event.target.value)}
                  maxLength={208}
                  disabled={disabled}
                  {...errorProps("totp.seed")}
                />
                <p className="text-muted-foreground text-xs">{t("totpHelp")}</p>
                {failure("totp.seed")}
              </div>
              <div className="grid gap-3 sm:grid-cols-3">
                {(
                  [
                    ["algorithm", "totpAlgorithm", ["SHA1", "SHA256", "SHA512"]],
                    ["digits", "totpDigits", [6, 8]],
                    ["period_seconds", "totpPeriod", [30, 60]],
                  ] as const
                ).map(([field, label, options]) => (
                  <div className="space-y-2" key={field}>
                    <Label htmlFor={id(`totp.${field}`)}>{t(label)}</Label>
                    <Select
                      value={String(totp[field])}
                      onValueChange={(next) =>
                        setTotp(field, field === "algorithm" ? next : Number(next))
                      }
                      disabled={disabled}
                    >
                      <SelectTrigger id={id(`totp.${field}`)} {...errorProps(`totp.${field}`)}>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {options.map((option) => (
                          <SelectItem value={String(option)} key={option}>
                            {field === "period_seconds"
                              ? t("seconds", { count: option })
                              : String(option)}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    {failure(`totp.${field}`)}
                  </div>
                ))}
              </div>
              {failure("totp")}
            </div>
          )}
        </>
      ) : (
        <fieldset className="space-y-3" disabled={disabled}>
          <legend className="mb-2 text-sm font-medium">{t("contactFields")}</legend>
          <p className="text-muted-foreground text-xs">{t("contactFieldsHelp")}</p>
          {BROWSER_PROFILE_FIELDS.map((field) => (
            <div className="space-y-2" key={field}>
              <div className="flex items-center gap-2">
                <Checkbox
                  id={id(`use-${field}`)}
                  checked={Object.hasOwn(fields, field)}
                  disabled={disabled}
                  onCheckedChange={(checked) => {
                    const next = { ...fields };
                    if (checked === true) next[field] = "";
                    else delete next[field];
                    set("fields", next);
                  }}
                />
                <Label htmlFor={id(`use-${field}`)}>
                  {t("useField", { field: t(`fieldChoices.${field}`) })}
                </Label>
              </div>
              {Object.hasOwn(fields, field) && (
                <div className="space-y-2 pl-6">
                  <Label htmlFor={id(`fields.${field}`)}>{t(`fields.${field}`)}</Label>
                  <Input
                    id={id(`fields.${field}`)}
                    value={typeof fields[field] === "string" ? fields[field] : ""}
                    onChange={(event) => set("fields", { ...fields, [field]: event.target.value })}
                    maxLength={1024}
                    autoComplete="off"
                    disabled={disabled}
                    {...errorProps(`fields.${field}`)}
                  />
                  {failure(`fields.${field}`)}
                </div>
              )}
            </div>
          ))}
          {failure("fields")}
        </fieldset>
      )}
    </div>
  );
}
