"use client";

import Link from "next/link";
import { Check, FileText, Plus } from "lucide-react";

import {
  Badge,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Switch,
  Pager,
  PICKER_PAGE_SIZE,
  SearchInput,
  useChosenFirst,
  useListControls,
} from "@/components/ui";
import { GroupsChip } from "@/components/sharing/audience-chip";
import type { ContextSettings } from "@/lib/context-settings";
import { ROUTES } from "@/lib/constants";
import { cn } from "@/lib/utils";
import type { ContextFileSummary } from "@/types/providers";
import { useTranslations } from "next-intl";

interface ContextGalleryProps {
  settings?: ContextSettings;
  onSettingsChange?: (settings: ContextSettings) => void;
  files: ContextFileSummary[];
  /** How many the organization has, which may exceed what was fetched. */
  total: number;
  /** `spec.context_ids`. */
  selectedIds: string[];
  onToggle: (fileId: string) => void;
  disabled?: boolean;
}

/**
 * Every context file the organization has, as a gallery to pick from.
 *
 * A gallery rather than a checkbox list for the same reason skills use one: a
 * file is chosen on what its description says, then the selected tile exposes
 * its per-agent mode and availability. Files that no longer exist are named rather than dropped, so
 * the Builder shows an orphan rather than letting it vanish silently.
 */
export function ContextGallery({
  files,
  total,
  selectedIds,
  onToggle,
  disabled,
  settings = {},
  onSettingsChange,
}: ContextGalleryProps) {
  const t = useTranslations("agents");
  const tContext = useTranslations("context");
  const chosen = new Set(selectedIds);
  const known = new Set(files.map((file) => file.id));
  const orphaned = files.length >= total ? selectedIds.filter((id) => !known.has(id)) : [];

  const ordered = useChosenFirst(files, selectedIds);
  const list = useListControls({
    items: ordered,
    pageSize: PICKER_PAGE_SIZE,
    matches: (file, query) =>
      file.name.toLowerCase().includes(query) ||
      (file.description ?? "").toLowerCase().includes(query),
  });

  if (files.length === 0) {
    return (
      <div className="border-border rounded-lg border border-dashed p-6 text-center">
        <FileText className="text-muted-foreground mx-auto h-6 w-6" />
        <p className="text-muted-foreground mt-2 text-sm">{t("organizationHasNoContext")}</p>
        <Link
          href={ROUTES.CONTEXT}
          className="mt-3 inline-flex items-center gap-1.5 text-sm underline underline-offset-4"
        >
          <Plus className="h-3.5 w-3.5" />
          {t("addOne")}
        </Link>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {files.length > 8 && (
        <SearchInput value={list.query} onChange={list.setQuery} placeholder={t("searchContext")} />
      )}

      <div className="grid gap-2 sm:grid-cols-2">
        {list.visible.map((file) => {
          const isOn = chosen.has(file.id);
          return (
            <div key={file.id} className="overflow-hidden rounded-xl border">
              <button
                type="button"
                role="checkbox"
                aria-checked={isOn}
                aria-label={file.name}
                disabled={disabled}
                onClick={() => onToggle(file.id)}
                className={cn(
                  "flex w-full items-start gap-3 p-4 text-left transition-colors",
                  isOn ? "bg-foreground/[0.04]" : "hover:bg-muted/40",
                  disabled && "cursor-not-allowed opacity-60",
                )}
              >
                <span
                  className={cn(
                    "mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded border",
                    isOn ? "border-brand bg-brand text-brand-foreground" : "border-input",
                  )}
                >
                  {isOn && <Check className="h-3 w-3" />}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-sm font-medium">{file.name}</span>
                    <Badge
                      variant={
                        (settings[file.id]?.mode ?? file.mode) === "inject"
                          ? "secondary"
                          : "outline"
                      }
                    >
                      {tContext(
                        (settings[file.id]?.mode ?? file.mode) === "inject"
                          ? "modeInject"
                          : "modeLink",
                      )}
                    </Badge>
                    {!(settings[file.id]?.enabled ?? file.enabled) && (
                      <Badge variant="outline">{t("disabled")}</Badge>
                    )}
                    <GroupsChip groups={file.shared_groups} />
                  </span>
                  {file.description !== null && (
                    <span className="text-muted-foreground mt-1 block text-sm">
                      {file.description}
                    </span>
                  )}
                </span>
              </button>
              {isOn && onSettingsChange && (
                <div className="space-y-3 border-t p-4">
                  <div className="flex items-center justify-between gap-3">
                    <Label htmlFor={`use-context-${file.id}`}>{tContext("useForAgent")}</Label>
                    <Switch
                      id={`use-context-${file.id}`}
                      disabled={disabled}
                      checked={settings[file.id]?.enabled ?? file.enabled}
                      onCheckedChange={(enabled) =>
                        onSettingsChange({
                          ...settings,
                          [file.id]: { mode: settings[file.id]?.mode ?? file.mode, enabled },
                        })
                      }
                    />
                  </div>
                  <Select
                    value={settings[file.id]?.mode ?? file.mode}
                    disabled={disabled || !(settings[file.id]?.enabled ?? file.enabled)}
                    onValueChange={(mode) => {
                      if (mode === "inject" || mode === "link")
                        onSettingsChange({
                          ...settings,
                          [file.id]: { mode, enabled: settings[file.id]?.enabled ?? file.enabled },
                        });
                    }}
                  >
                    <SelectTrigger aria-label={tContext("usageForAgent", { name: file.name })}>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="inject">{tContext("modeInject")}</SelectItem>
                      <SelectItem value="link">{tContext("modeLink")}</SelectItem>
                    </SelectContent>
                  </Select>
                  <p className="text-muted-foreground text-xs">
                    {tContext(
                      (settings[file.id]?.mode ?? file.mode) === "inject"
                        ? "modeInjectHint"
                        : "modeLinkHint",
                    )}
                  </p>
                </div>
              )}
            </div>
          );
        })}
      </div>

      <Pager
        page={list.page}
        pageCount={list.pageCount}
        matched={list.matched}
        total={list.total}
        onPage={list.setPage}
        counted={t("contextCount", { count: list.total })}
      />

      {orphaned.length > 0 && (
        <p className="text-muted-foreground text-xs">
          {t("orphanedContext", { count: orphaned.length })}{" "}
          <span className="font-mono break-all">{orphaned.join(", ")}</span>
        </p>
      )}

      <p className="text-muted-foreground text-xs">
        {t.rich("contextLoadingHint", {
          link: (chunks) => (
            <Link href={ROUTES.CONTEXT} className="underline underline-offset-4">
              {chunks}
            </Link>
          ),
        })}
      </p>
    </div>
  );
}
