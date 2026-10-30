"use client";

import { FolderOpen } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  Button,
  FormField,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { useLocalFolders } from "@/hooks/use-desktop";
import { useShell } from "@/hooks/use-shell";
import type { LocalTarget } from "@/lib/desktop/commands";

/** Sentinel for "the agent's own sandbox" - a Select item may not be empty. */
const SANDBOX = "__sandbox__";

/**
 * Where a trigger that acts as its creator works: the agent's sandbox, or a
 * folder on the creator's own computer (#2305).
 *
 * Only the creator sees it, only once the trigger acts as them, and folders are
 * offered only where they can be granted - the desktop app on that computer.
 * Elsewhere a trigger already pointed at a folder says so and can be moved back
 * to the sandbox, which needs no computer.
 */
export function LocalTargetField({
  value,
  onChange,
  visible,
}: {
  value: LocalTarget | null;
  onChange: (value: LocalTarget | null) => void;
  /** The trigger acts as the person looking, who is its creator. */
  visible: boolean;
}) {
  const t = useTranslations("triggers.local");
  const tModes = useTranslations("chat.controls.workOn.mode");
  const shell = useShell();
  const { state, pick } = useLocalFolders();
  if (!visible || (shell === null && value === null)) return null;

  if (shell === null && value !== null) {
    return (
      <FormField label={t("label")} htmlFor="trigger-local" description={t("elsewhereHint")}>
        <div className="flex items-center justify-between gap-2 text-sm" id="trigger-local">
          <span className="truncate" title={value.folder}>
            {value.folder} · {tModes(value.mode)}
          </span>
          <Button variant="outline" size="sm" onClick={() => onChange(null)}>
            {t("useSandbox")}
          </Button>
        </div>
      </FormField>
    );
  }

  const grants = state.data?.grants ?? [];
  return (
    <FormField label={t("label")} htmlFor="trigger-local" description={t("hint")}>
      <div className="flex items-center gap-2">
        <Select
          value={value?.folder ?? SANDBOX}
          onValueChange={(next) => {
            const grant = grants.find((item) => item.path === next);
            onChange(grant ? { folder: grant.path, mode: grant.mode } : null);
          }}
        >
          <SelectTrigger id="trigger-local" className="min-w-0 flex-1">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={SANDBOX}>{t("sandbox")}</SelectItem>
            {grants.map((grant) => (
              <SelectItem key={grant.path} value={grant.path}>
                {grant.path} · {tModes(grant.mode)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Button
          variant="outline"
          size="sm"
          disabled={pick.isPending}
          onClick={() =>
            pick.mutate("workspace_write", {
              onSuccess: (grant) => {
                if (grant) onChange({ folder: grant.path, mode: grant.mode });
              },
            })
          }
        >
          <FolderOpen className="h-3.5 w-3.5" aria-hidden />
          {t("pick")}
        </Button>
      </div>
    </FormField>
  );
}
