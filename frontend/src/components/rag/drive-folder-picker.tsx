"use client";

import { Check, ChevronRight, Folder, HardDrive } from "lucide-react";
import { useState } from "react";
import { useTranslations } from "next-intl";

import { Button, Label } from "@/components/ui";
import { useDriveFolders } from "@/hooks/use-drive-folders";
import { getErrorMessage } from "@/lib/api-error";
import type { DriveFolderItem } from "@/lib/rag-api";
import { cn } from "@/lib/utils";

/** A level the picker has walked into. The root is the empty path, not a level. */
interface Level extends DriveFolderItem {
  kind: "drive" | "folder";
}

/** The `parent` the API lists a level by: a shared drive is `drive:<id>`, a folder its id. */
function parentOf(level: Level | null): string {
  if (level === null) return "root";
  return level.kind === "drive" ? `drive:${level.id}` : level.id;
}

/**
 * Pick the Drive folder a source syncs, by walking the connected account's Drive.
 *
 * Shows My Drive's top level with the shared drives beside it, and each folder
 * below. Selecting writes the folder's id to `value` (`config.folder_id`); the
 * root has nothing to select, so the action appears once a level is open.
 */
export function DriveFolderPicker({
  account,
  value,
  onSelect,
  error,
}: {
  account: string;
  /** The `folder_id` the source will submit. */
  value: string;
  onSelect: (folderId: string) => void;
  /** What the server said about `folder_id`, if it refused one. */
  error?: string;
}) {
  const t = useTranslations("rag");
  const tErrors = useTranslations("errors");
  const [path, setPath] = useState<Level[]>([]);
  const [chosen, setChosen] = useState<DriveFolderItem | null>(null);
  const current = path[path.length - 1] ?? null;
  const listing = useDriveFolders(account, parentOf(current));
  const atRoot = current === null;
  const drives = atRoot ? (listing.data?.drives ?? []) : [];
  const folders = listing.data?.folders ?? [];
  // A saved folder_id is shown by name only once this picker has seen the name
  // (selected it, or walked into it). Until then the raw id stays out of view.
  const chosenName = [chosen, ...path].find((item) => item?.id === value)?.name;
  const chosenLabel =
    chosenName === undefined
      ? t("driveFolderChosenUnnamed")
      : t("driveFolderChosen", { name: chosenName });

  return (
    <div className="space-y-2">
      <Label>
        {t("driveFolderLabel")}
        <span className="text-muted-foreground ml-0.5">*</span>
      </Label>

      <nav aria-label={t("driveFolderPath")}>
        <ol className="flex min-w-0 flex-wrap items-center gap-1 text-sm">
          <li>
            <button
              type="button"
              aria-current={atRoot ? "location" : undefined}
              onClick={() => setPath([])}
              className={cn(
                "rounded px-1 py-0.5 hover:underline",
                atRoot ? "text-foreground font-medium" : "text-muted-foreground",
              )}
            >
              {t("driveFolderRoot")}
            </button>
          </li>
          {path.map((level, index) => {
            const last = index === path.length - 1;
            return (
              <li key={`${level.kind}:${level.id}`} className="flex min-w-0 items-center gap-1">
                <ChevronRight aria-hidden className="text-muted-foreground h-3 w-3 shrink-0" />
                <button
                  type="button"
                  aria-current={last ? "location" : undefined}
                  onClick={() => setPath(path.slice(0, index + 1))}
                  className={cn(
                    "max-w-[12rem] truncate rounded px-1 py-0.5 hover:underline",
                    last ? "text-foreground font-medium" : "text-muted-foreground",
                  )}
                >
                  {level.name}
                </button>
              </li>
            );
          })}
        </ol>
      </nav>

      <div
        className="border-foreground/10 max-h-64 min-h-24 scrollbar-thin overflow-y-auto rounded-xl border"
        aria-busy={listing.isLoading}
      >
        {listing.isLoading ? (
          <p className="text-muted-foreground p-4 text-sm">{t("driveFolderLoading")}</p>
        ) : listing.error ? (
          <div className="flex flex-col items-start gap-2 p-4">
            <p role="alert" className="text-destructive text-sm">
              {getErrorMessage(listing.error, tErrors)}
            </p>
            <Button type="button" variant="outline" size="sm" onClick={() => listing.refetch()}>
              {t("driveFolderRetry")}
            </Button>
          </div>
        ) : drives.length === 0 && folders.length === 0 ? (
          <p className="text-muted-foreground p-4 text-sm">{t("driveFolderEmpty")}</p>
        ) : (
          <div className="divide-foreground/10 divide-y">
            {drives.length > 0 && (
              <DriveRows
                heading={t("driveSectionShared")}
                items={drives}
                icon={HardDrive}
                onOpen={(item) => setPath([...path, { ...item, kind: "drive" }])}
              />
            )}
            {atRoot && folders.length > 0 && (
              <DriveRows
                heading={t("driveSectionMine")}
                items={folders}
                icon={Folder}
                onOpen={(item) => setPath([...path, { ...item, kind: "folder" }])}
              />
            )}
            {!atRoot && folders.length > 0 && (
              <DriveRows
                items={folders}
                icon={Folder}
                onOpen={(item) => setPath([...path, { ...item, kind: "folder" }])}
              />
            )}
          </div>
        )}
      </div>

      {current !== null && (
        <Button
          type="button"
          variant={value === current.id ? "default" : "outline"}
          size="sm"
          aria-pressed={value === current.id}
          onClick={() => {
            setChosen({ id: current.id, name: current.name });
            onSelect(current.id);
          }}
        >
          {value === current.id && <Check className="h-3.5 w-3.5" aria-hidden />}
          {t("driveFolderSelect")}
        </Button>
      )}

      <p
        className={cn(
          "text-sm",
          error === undefined ? "text-muted-foreground" : "text-destructive",
        )}
        role={error === undefined ? undefined : "alert"}
      >
        {error ?? (value === "" ? t("driveFolderNotChosen") : chosenLabel)}
      </p>
    </div>
  );
}

function DriveRows({
  heading,
  items,
  icon: Icon,
  onOpen,
}: {
  heading?: string;
  items: DriveFolderItem[];
  icon: typeof Folder;
  onOpen: (item: DriveFolderItem) => void;
}) {
  return (
    <div>
      {heading !== undefined && (
        <h4 className="text-muted-foreground px-4 pt-3 pb-1 text-xs font-medium">{heading}</h4>
      )}
      <ul>
        {items.map((item) => (
          <li key={item.id}>
            <button
              type="button"
              onClick={() => onOpen(item)}
              className="hover:bg-foreground/[0.04] focus-visible:bg-foreground/[0.04] flex w-full min-w-0 items-center gap-2 px-4 py-2.5 text-left text-sm focus-visible:outline-none"
            >
              <Icon aria-hidden className="text-muted-foreground h-4 w-4 shrink-0" />
              <span className="text-foreground min-w-0 flex-1 truncate">{item.name}</span>
              <ChevronRight aria-hidden className="text-muted-foreground h-3.5 w-3.5 shrink-0" />
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
