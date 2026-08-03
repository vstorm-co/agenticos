"use client";

import { Button } from "@/components/ui";
import { Check, Copy } from "lucide-react";
import { cn } from "@/lib/utils";
import { useCopyToClipboard } from "@/hooks/use-copy-to-clipboard";
import { useTranslations } from "next-intl";

interface CopyButtonProps {
  text: string;
  className?: string;
  size?: "sm" | "default";
}

export function CopyButton({ text, className, size = "sm" }: CopyButtonProps) {
  const t = useTranslations("chat.copy");
  const { copy, copied } = useCopyToClipboard();

  const handleCopy = async (e: React.MouseEvent) => {
    e.stopPropagation();
    await copy(text);
  };

  return (
    <Button
      variant="ghost"
      size={size}
      className={cn("h-6 w-6 p-0 opacity-0 transition-opacity group-hover:opacity-100", className)}
      onClick={handleCopy}
      title={copied ? t("copied") : t("copy")}
      aria-label={copied ? t("copiedToClipboard") : t("copyToClipboard")}
    >
      {copied ? (
        <Check className="text-success h-3.5 w-3.5" aria-hidden />
      ) : (
        <Copy className="h-3.5 w-3.5" aria-hidden />
      )}
    </Button>
  );
}
