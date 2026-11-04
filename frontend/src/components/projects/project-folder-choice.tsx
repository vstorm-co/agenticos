"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { FolderOpen, Unlink } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui";
import { useDeviceLink, useDeviceStatus, useLocalFolders } from "@/hooks/use-desktop";
import type { LocalMode, LocalTarget } from "@/lib/desktop/commands";

/** Selection always goes through the shell's approved folder grant. */
export function ProjectFolderChoice({
  value,
  onChange,
  disabled = false,
}: {
  value: LocalTarget | null;
  onChange: (target: LocalTarget | null) => void;
  disabled?: boolean;
}) {
  const t = useTranslations("projects.localFolder");
  const tw = useTranslations("chat.controls.workOn");
  const { data: device } = useDeviceStatus();
  const { link } = useDeviceLink();
  const { state, pick } = useLocalFolders();
  const modes = state.data?.modes ?? [];
  const [mode, setMode] = useState<LocalMode>(value?.mode ?? "read_only");
  const choice = useMutation({
    mutationFn: async (request: { mode: LocalMode; linked: boolean; save: typeof onChange }) => {
      if (!request.linked && !(await link.mutateAsync()).linked) return null;
      return pick.mutateAsync(request.mode);
    },
    // Stored on the mutation, so a native dialog may take focus or unmount the
    // panel without dropping the approved choice for the original project.
    onSuccess: (grant, request) => {
      if (grant) request.save({ folder: grant.path, mode: grant.mode });
    },
  });
  const busy = choice.isPending;
  return (
    <div className="border-border space-y-3 rounded-xl border p-4" data-tour="project-local-folder">
      <div className="space-y-1">
        <p className="text-sm font-medium">{t("title")}</p>
        <p className="text-muted-foreground text-xs leading-relaxed">{t("hint")}</p>
      </div>
      {value && (
        <p className="bg-muted rounded-lg px-3 py-2 font-mono text-xs break-all">{value.folder}</p>
      )}
      <div className="flex flex-wrap items-end gap-2">
        <label className="min-w-40 flex-1 space-y-1.5">
          <span className="text-sm font-medium">{tw("folderAccess")}</span>
          <select
            aria-label={tw("folderAccess")}
            value={mode}
            onChange={(event) => {
              const selected = modes.find((candidate) => candidate === event.target.value);
              if (selected) setMode(selected);
            }}
            disabled={disabled || busy}
            className="border-input bg-background h-10 w-full rounded-md border px-3 text-sm"
          >
            {modes.map((entry) => (
              <option key={entry} value={entry}>
                {tw(`mode.${entry}`)}
              </option>
            ))}
          </select>
        </label>
        <Button
          type="button"
          variant="outline"
          disabled={disabled || busy || device === undefined || !modes.includes(mode)}
          onClick={() => choice.mutate({ mode, linked: device?.linked === true, save: onChange })}
        >
          <FolderOpen aria-hidden />
          {busy ? t("connecting") : value ? t("change") : t("connect")}
        </Button>
        {value && (
          <Button
            type="button"
            variant="ghost"
            disabled={disabled || busy}
            onClick={() => onChange(null)}
          >
            <Unlink aria-hidden />
            {t("disconnect")}
          </Button>
        )}
      </div>
      <p className="text-muted-foreground text-xs leading-relaxed">{tw(`modeHint.${mode}`)}</p>
      {value && (
        <p className="text-muted-foreground text-xs">
          {t("activeAccess", { mode: tw(`mode.${value.mode}`) })}
        </p>
      )}
      {device?.linked && !device.connected && (
        <p role="status" className="text-muted-foreground text-xs">
          {tw("offline")}
        </p>
      )}
    </div>
  );
}
