"use client";

import { useState } from "react";
import { Check, Copy } from "lucide-react";
import { useTranslations } from "next-intl";

/** A block of code with a button that copies it - a curl call, a base URL. */
export function CopyCode({ code }: { code: string }) {
  const t = useTranslations("common");
  const [copied, setCopied] = useState(false);

  async function copy() {
    await navigator.clipboard.writeText(code);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  }

  return (
    <div className="bg-muted relative rounded-lg">
      <pre className="overflow-x-auto px-3 py-2.5 pr-20 font-mono text-xs leading-relaxed whitespace-pre">
        {code}
      </pre>
      <button
        type="button"
        onClick={copy}
        className="text-muted-foreground hover:text-foreground bg-background absolute top-1.5 right-1.5 inline-flex h-7 items-center gap-1 rounded-md border px-2 text-xs"
      >
        {copied ? (
          <Check className="h-3.5 w-3.5" aria-hidden />
        ) : (
          <Copy className="h-3.5 w-3.5" aria-hidden />
        )}
        {copied ? t("copied") : t("copy")}
      </button>
    </div>
  );
}
