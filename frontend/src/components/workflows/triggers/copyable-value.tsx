"use client";

import { Check, Copy } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { Button, Input, Label } from "@/components/ui";
import { useCopyToClipboard } from "@/hooks/use-copy-to-clipboard";

/** A read-only value with a copy button: a webhook URL, an API call. */
export function CopyableValue({ id, label, value }: { id: string; label: string; value: string }) {
  const t = useTranslations("pages.workflows");
  const common = useTranslations("common");
  const { copy, copied } = useCopyToClipboard();

  async function copyValue() {
    if (!(await copy(value))) toast.error(common("copyFailed"));
  }

  return (
    <div className="space-y-1">
      <Label htmlFor={id}>{label}</Label>
      <div className="flex gap-2">
        <Input id={id} value={value} readOnly className="flex-1 font-mono text-base md:text-xs" />
        <Button
          type="button"
          variant="outline"
          size="icon"
          aria-label={copied ? t("copied") : t("copyNamed", { name: label })}
          onClick={copyValue}
        >
          {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
        </Button>
      </div>
    </div>
  );
}
