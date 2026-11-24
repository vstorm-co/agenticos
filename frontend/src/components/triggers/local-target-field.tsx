"use client";

import { FolderOpen } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button, Checkbox, FormField, Label } from "@/components/ui";
import { useRoutineLocalWork } from "@/hooks/use-routine-local-work";
import type { LocalTarget } from "@/lib/desktop/commands";

/**
 * A folder preview grants nothing. Saving reuses the person's permission for every
 * routine when it covers the folder, and otherwise asks for it once, natively.
 */
export function LocalTargetField({
  value,
  onChange,
  visible,
}: {
  value: LocalTarget | null;
  onChange: (value: LocalTarget | null) => void;
  visible: boolean;
}) {
  const t = useTranslations("triggers.local");
  const { available, identity, supportsWrites, pick, grants } = useRoutineLocalWork();
  const everyRoutine = grants.data?.find((grant) => grant.routine_id === null);
  if (!visible || (!available && value === null)) return null;
  const editable = available && identity?.device_id === value?.device_id;
  function operations(write: boolean, execute: boolean) {
    if (!value || !editable) return;
    onChange({
      ...value,
      folder: value.folder,
      device_id: value.device_id,
      mode: write ? "workspace_write" : "read_only",
      operations: { read: true, write, execute },
    });
  }
  return (
    <FormField
      label={t("label")}
      htmlFor="trigger-local"
      description={t(available ? "routineHint" : "elsewhereHint")}
    >
      <div id="trigger-local" className="space-y-3">
        <div className="flex items-center gap-2">
          <span className="min-w-0 flex-1 truncate text-sm" title={value?.folder}>
            {value?.folder ?? t("sandbox")}
          </span>
          {value && (
            <Button variant="outline" size="sm" onClick={() => onChange(null)}>
              {t("useSandbox")}
            </Button>
          )}
          {available && everyRoutine && identity && value?.folder !== everyRoutine.root && (
            <Button
              variant="outline"
              size="sm"
              onClick={() =>
                onChange({
                  folder: everyRoutine.root,
                  device_id: identity.device_id,
                  mode: everyRoutine.operations.write ? "workspace_write" : "read_only",
                  operations: everyRoutine.operations,
                })
              }
            >
              {t("useAllowed")}
            </Button>
          )}
          {available && (
            <Button
              variant="outline"
              size="sm"
              disabled={pick.isPending}
              onClick={() =>
                pick.mutate(undefined, {
                  onSuccess: (folder) => {
                    if (folder && identity)
                      onChange({
                        folder,
                        device_id: identity.device_id,
                        mode: "read_only",
                        operations: { read: true, write: false, execute: false },
                      });
                  },
                })
              }
            >
              <FolderOpen className="h-3.5 w-3.5" aria-hidden />
              {t("pick")}
            </Button>
          )}
        </div>
        {value && (
          <div className="flex flex-wrap gap-4 text-sm">
            <Label className="flex items-center gap-2">
              <Checkbox checked disabled />
              {t("read")}
            </Label>
            <Label className="flex items-center gap-2">
              <Checkbox
                checked={value.operations?.write ?? false}
                disabled={!editable || !supportsWrites}
                onCheckedChange={(checked) => operations(checked === true, false)}
              />
              {t("write")}
            </Label>
            <Label className="flex items-center gap-2">
              <Checkbox
                checked={value.operations?.execute ?? false}
                disabled={!editable || !supportsWrites}
                onCheckedChange={(checked) =>
                  operations(checked === true || !!value.operations?.write, checked === true)
                }
              />
              {t("execute")}
            </Label>
          </div>
        )}
        {value && !value.routine_grant && (
          <p className="text-muted-foreground text-xs">{t("reviewRequired")}</p>
        )}
      </div>
    </FormField>
  );
}
