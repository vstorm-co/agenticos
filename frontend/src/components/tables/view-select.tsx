"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Plus, Trash2 } from "lucide-react";
import {
  Button,
  ConfirmDialog,
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Input,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { DIALOG_CONFIRM } from "@/lib/dialog-sizes";
import type { TableViewRead, ViewKind, ViewVisibility } from "@/types/tables";

/**
 * The saved-view picker for the active kind, and its owner-only rename/delete
 * controls. Gated on `view.can_manage`, never on `table.can_edit`: a table
 * editor another member shared a view with may not silently repoint their
 * saved filter (see `docs/virtual-tables.md#saved-views`).
 */
export function ViewSelect({
  kind,
  views,
  activeViewId,
  onSelect,
  onCreate,
  onRename,
  onDelete,
  canCreate,
}: {
  kind: ViewKind;
  views: TableViewRead[];
  activeViewId: string | null;
  onSelect: (viewId: string | null) => void;
  onCreate: (name: string, visibility: ViewVisibility) => void;
  onRename: (viewId: string, name: string) => void;
  onDelete: (viewId: string) => void;
  canCreate: boolean;
}) {
  const t = useTranslations("pages.tables.views");
  const [createOpen, setCreateOpen] = useState(false);
  const [renaming, setRenaming] = useState<TableViewRead | null>(null);
  const [deleting, setDeleting] = useState<TableViewRead | null>(null);
  const [draftName, setDraftName] = useState("");
  const [draftVisibility, setDraftVisibility] = useState<ViewVisibility>("private");

  const active = views.find((view) => view.id === activeViewId) ?? null;

  return (
    <div className="flex items-center gap-1.5">
      <Select
        value={activeViewId ?? "__default__"}
        onValueChange={(id) => onSelect(id === "__default__" ? null : id)}
      >
        <SelectTrigger className="w-44" aria-label={t("selectViewFor", { kind })}>
          <SelectValue placeholder={t("unsavedView")} />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="__default__">{t("unsavedView")}</SelectItem>
          {views.map((view) => (
            <SelectItem key={view.id} value={view.id}>
              {view.name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {canCreate && (
        <Button
          type="button"
          variant="outline"
          size="sm"
          data-tour="table-view-new"
          onClick={() => {
            setDraftName("");
            setDraftVisibility("private");
            setCreateOpen(true);
          }}
          aria-label={t("newView")}
        >
          <Plus className="h-4 w-4" />
        </Button>
      )}
      {active?.can_manage && (
        <>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => {
              setDraftName(active.name);
              setRenaming(active);
            }}
          >
            {t("rename")}
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            aria-label={t("delete")}
            onClick={() => setDeleting(active)}
          >
            <Trash2 className="h-4 w-4" />
          </Button>
        </>
      )}

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent className={DIALOG_CONFIRM}>
          <DialogHeader>
            <DialogTitle>{t("newView")}</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <Input
              value={draftName}
              onChange={(event) => setDraftName(event.target.value)}
              placeholder={t("namePlaceholder")}
              aria-label={t("namePlaceholder")}
            />
            <Select
              value={draftVisibility}
              onValueChange={(next) => setDraftVisibility(next as ViewVisibility)}
            >
              <SelectTrigger aria-label={t("visibilityLabel")}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="private">{t("private")}</SelectItem>
                <SelectItem value="shared">{t("shared")}</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setCreateOpen(false)}>
              {t("cancel")}
            </Button>
            <Button
              type="button"
              disabled={!draftName.trim()}
              onClick={() => {
                onCreate(draftName.trim(), draftVisibility);
                setCreateOpen(false);
              }}
            >
              {t("save")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/*
        Save and Cancel both clear `renaming` directly, so this handler only
        ever fires from an in-dialog close this component did not initiate
        (Escape, the overlay, the close button) - always with `open: false`,
        since nothing here reopens the dialog through Radix. Clearing
        unconditionally is therefore equivalent to checking `open` first.
      */}
      <Dialog open={!!renaming} onOpenChange={() => setRenaming(null)}>
        <DialogContent className={DIALOG_CONFIRM}>
          <DialogHeader>
            <DialogTitle>{t("rename")}</DialogTitle>
          </DialogHeader>
          <Input
            value={draftName}
            onChange={(event) => setDraftName(event.target.value)}
            aria-label={t("namePlaceholder")}
          />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setRenaming(null)}>
              {t("cancel")}
            </Button>
            <Button
              type="button"
              disabled={!draftName.trim()}
              onClick={() => {
                // This button only exists while the dialog is open, and the
                // dialog is only open while `renaming` is set (`open={!!renaming}`
                // above), so `renaming` is never null here.
                onRename(renaming!.id, draftName.trim());
                setRenaming(null);
              }}
            >
              {t("save")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={!!deleting}
        onOpenChange={(open) => !open && setDeleting(null)}
        title={t("deleteTitle")}
        description={t("deleteDescription", { name: deleting?.name ?? "" })}
        confirmLabel={t("delete")}
        destructive
        onConfirm={() => {
          // The confirm button only exists while `ConfirmDialog` is open, and
          // it is only open while `deleting` is set (`open={!!deleting}`
          // above), so `deleting` is never null here.
          onDelete(deleting!.id);
          setDeleting(null);
        }}
      />
    </div>
  );
}
