"use client";

import { Plug } from "lucide-react";
import { Button } from "@/components/ui";
import { useManagedAppConnect } from "@/hooks/use-managed-app-connect";

export function ManagedAppConnectButton({
  catalogKey,
  label,
  disabled,
  keepThisTab,
}: {
  catalogKey: string;
  label: string;
  disabled?: boolean;
  keepThisTab?: boolean;
}) {
  const connect = useManagedAppConnect();
  return (
    <Button
      type="button"
      size="sm"
      disabled={disabled}
      onClick={() => connect(catalogKey, { keepThisTab })}
    >
      <Plug aria-hidden />
      {label}
    </Button>
  );
}
