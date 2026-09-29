"use client";

import { useState } from "react";
import { Check, Copy } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button, Input, Label } from "@/components/ui";

/** A read-only value with a copy button: a webhook URL, an API call. */
export function CopyableValue({ id, label, value }: { id: string; label: string; value: string }) {
  const t = useTranslations("pages.workflows");
  const [copied, setCopied] = useState(false);

  async function copy() {
    await navigator.clipboard.writeText(value);
    setCopied(true);
  }

  return (
    <div className="space-y-1">
      <Label htmlFor={id}>{label}</Label>
      <div className="flex gap-2">
        <Input id={id} value={value} readOnly className="flex-1 font-mono text-xs" />
        <Button
          type="button"
          variant="outline"
          size="icon"
          aria-label={copied ? t("copied") : t("copyNamed", { name: label })}
          onClick={copy}
        >
          {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
        </Button>
      </div>
    </div>
  );
}
