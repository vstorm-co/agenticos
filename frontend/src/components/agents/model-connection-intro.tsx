"use client";

import type { ReactNode } from "react";
import { ProviderIcon } from "@/components/vault/provider-icon";

/** Consistent connection entry for subscription sign-ins and provider credentials. */
export function ModelConnectionIntro({
  provider,
  name,
  description,
  children,
}: {
  provider: string;
  name: string;
  description?: string;
  children: ReactNode;
}) {
  return (
    <div className="mx-auto flex max-w-sm flex-col items-center gap-3 py-6 text-center">
      <ProviderIcon provider={provider} className="size-10" />
      <h3 className="text-base font-semibold">{name}</h3>
      {description && <p className="text-muted-foreground text-sm">{description}</p>}
      <div className="w-full [&>div]:justify-center">{children}</div>
    </div>
  );
}
