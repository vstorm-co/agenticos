"use client";

import Link from "next/link";
import { Server } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  Badge,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { usePermissions, useSandboxConnections } from "@/hooks";
import { ROUTES } from "@/lib/constants";
import { Perm } from "@/types/permissions";

/** The option that leaves the choice to the organization's default host. */
const DEFAULT = "__default__";

export interface SandboxConnectionPickerProps {
  /** What the control is called: the field's own name, or the picker's when it has none. */
  label?: string;
  /** The chosen connection's id, or null for the organization's default. */
  value: string | null;
  onChange: (connectionId: string | null) => void;
  disabled?: boolean;
  error?: string;
}

/**
 * Which sandbox host a script step runs on, or the organization's default.
 *
 * Only a `docker` connection - a `sandboxd` service - runs workflow scripts, so
 * a Daytona one is not offered. Listing hosts needs `connections:view`; a member
 * without it keeps the default, and is told why instead of shown an empty list.
 */
export function SandboxConnectionPicker({
  value,
  onChange,
  disabled,
  error,
  label,
}: SandboxConnectionPickerProps) {
  const t = useTranslations("workflows");
  const caption = label ?? t("pickerHostLabel");
  const { can } = usePermissions();
  const mayView = can(Perm.connectionsView);
  const { connections, isLoading } = useSandboxConnections(mayView);
  const hosts = connections.filter((connection) => connection.kind === "docker");
  const orphaned =
    value !== null && !isLoading && !hosts.some((connection) => connection.id === value);

  if (!mayView) {
    return <p className="text-muted-foreground text-xs">{t("pickerHostNeedsPermission")}</p>;
  }

  return (
    <div className="space-y-2">
      <Label>{caption}</Label>
      <Select
        value={value ?? DEFAULT}
        onValueChange={(next) => onChange(next === DEFAULT ? null : next)}
        disabled={disabled}
      >
        <SelectTrigger aria-label={caption}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={DEFAULT}>{t("pickerHostDefault")}</SelectItem>
          {hosts.map((connection) => (
            <SelectItem key={connection.id} value={connection.id}>
              <span className="flex items-center gap-2">
                <Server className="h-3.5 w-3.5 shrink-0" />
                <span className="truncate">{connection.name}</span>
                {connection.is_default && (
                  <Badge variant="outline">{t("pickerHostIsDefault")}</Badge>
                )}
                {!connection.is_active && <Badge variant="secondary">{t("pickerHostOff")}</Badge>}
              </span>
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {hosts.length === 0 && !isLoading && (
        <p className="text-muted-foreground text-xs">
          {t("pickerHostsEmpty")}{" "}
          <Link href={ROUTES.SANDBOXES} className="underline underline-offset-2">
            {t("pickerHostsAdd")}
          </Link>
        </p>
      )}
      {orphaned && <p className="text-foreground/70 text-xs">{t("pickerHostOrphaned")}</p>}
      {error !== undefined && <p className="text-destructive text-xs">{error}</p>}
    </div>
  );
}
