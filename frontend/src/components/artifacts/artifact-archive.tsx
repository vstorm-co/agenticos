"use client";

import { Archive, ArchiveRestore } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";

import { Alert, AlertDescription, AlertTitle, Button, ConfirmDialog } from "@/components/ui";

/** Asks before a page is archived, saying what is kept, what stops, and the way back. */
export function ArchiveArtifactDialog({
  open,
  onOpenChange,
  title,
  loading,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  loading: boolean;
  onConfirm: () => void;
}) {
  const t = useTranslations("artifacts");
  return (
    <ConfirmDialog
      open={open}
      onOpenChange={onOpenChange}
      title={t("archiveTitle", { title })}
      description={t("archiveWhy")}
      confirmLabel={t("archive")}
      loading={loading}
      onConfirm={onConfirm}
    />
  );
}

/** Asks before a page is deleted for good, saying what goes with it. */
export function DeleteArtifactDialog({
  open,
  onOpenChange,
  title,
  loading,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  loading: boolean;
  onConfirm: () => void | Promise<void>;
}) {
  const t = useTranslations("artifacts");
  const tc = useTranslations("common");
  return (
    <ConfirmDialog
      open={open}
      onOpenChange={onOpenChange}
      title={t("deleteTitle", { title })}
      description={t("deleteWhy")}
      confirmLabel={tc("delete")}
      destructive
      loading={loading}
      onConfirm={onConfirm}
    />
  );
}

/**
 * What an editor sees in place of an archived page: since when, and Restore.
 *
 * Only an editor is ever shown an archived page - the server answers anybody
 * else as though it were not there - so the way back is always offered.
 */
export function ArchivedArtifactNotice({
  archivedAt,
  restoring,
  onRestore,
}: {
  archivedAt: string;
  restoring: boolean;
  onRestore: () => void;
}) {
  const t = useTranslations("artifacts");
  const format = useFormatter();
  const when = format.dateTime(new Date(archivedAt), { dateStyle: "medium" });
  return (
    <Alert variant="warning" className="max-w-xl">
      <Archive aria-hidden="true" className="size-4" />
      {/* One wrapper after the icon: the Alert indents every sibling of its icon. */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <AlertTitle>{t("archivedOn", { when })}</AlertTitle>
          <AlertDescription>{t("archivedWhy")}</AlertDescription>
        </div>
        <Button variant="outline" size="sm" disabled={restoring} onClick={onRestore}>
          <ArchiveRestore className="h-4 w-4" /> {t("unarchive")}
        </Button>
      </div>
    </Alert>
  );
}
