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
        <Input id={id} readOnly value={url} className="font-mono text-base md:text-xs" />
        <CopyButton text={url} label={copyLabel} className="h-8 w-8 opacity-100" />
      </div>
    </div>
  );
}
