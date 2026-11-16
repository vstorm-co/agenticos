"use client";

import { useTranslations } from "next-intl";
import {
  FormField,
  Input,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";

interface Props {
  config: Record<string, unknown>;
  onChange: (config: Record<string, unknown>) => void;
}

/** The generic webhook supports the legacy relay signature or a raw-body HMAC. */
export function WebhookSignatureFields({ config, onChange }: Props) {
  const t = useTranslations("triggers");
  const scheme = typeof config.signature_scheme === "string" ? config.signature_scheme : "legacy";
  return (
    <div className="space-y-3">
      <FormField label={t("signatureScheme")} htmlFor="webhook-signature-scheme">
        <Select
          value={scheme}
          onValueChange={(value) => {
            const next = { ...config };
            if (value === "legacy") {
              delete next.signature_scheme;
              delete next.signature_header;
            } else {
              next.signature_scheme = value;
            }
            onChange(next);
          }}
        >
          <SelectTrigger id="webhook-signature-scheme">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="legacy">{t("signatureLegacy")}</SelectItem>
            <SelectItem value="hmac-sha256-hex">{t("signatureHex")}</SelectItem>
            <SelectItem value="hmac-sha256-base64">{t("signatureBase64")}</SelectItem>
          </SelectContent>
        </Select>
      </FormField>
      {scheme !== "legacy" && (
        <FormField
          label={t("signatureHeader")}
          htmlFor="webhook-signature-header"
          description={t("signatureRawHelp")}
        >
          <Input
            id="webhook-signature-header"
            value={typeof config.signature_header === "string" ? config.signature_header : ""}
            onChange={(event) => onChange({ ...config, signature_header: event.target.value })}
            maxLength={128}
          />
        </FormField>
      )}
    </div>
  );
}

/** Match the server's HTTP header token and length constraints. */
export function webhookSignatureValid(config: Record<string, unknown>): boolean {
  if (!config.signature_scheme || config.signature_scheme === "legacy") return true;
  return (
    typeof config.signature_header === "string" &&
    /^[!#$%&'*+.^_`|~0-9A-Za-z-]{1,128}$/.test(config.signature_header)
  );
}
