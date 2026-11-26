"use client";

import { useId } from "react";
import { CopyButton } from "@/components/chat/copy-button";
import { Input, Label } from "@/components/ui";

export function ShareLinkField({
  label,
  url,
  copyLabel,
}: {
  label: string;
  url: string;
  copyLabel?: string;
}) {
  const id = useId();
  return (
    <div className="space-y-2">
      <Label htmlFor={id}>{label}</Label>
      <div className="flex items-center gap-2">
        <Input
          id={id}
          readOnly
          value={url}
          className="h-10 min-w-0 font-mono text-base md:text-xs pointer-coarse:h-11"
        />
        <CopyButton
          text={url}
          label={copyLabel}
          className="size-10 shrink-0 opacity-100 pointer-coarse:size-11"
        />
      </div>
    </div>
  );
}
