"use client";

import { useQuery } from "@tanstack/react-query";
import { FileX } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui";
import { DIALOG_CONFIRM } from "@/lib/dialog-sizes";
import { qk } from "@/lib/query-keys";
import { findKBDocument } from "@/lib/rag-api";

import { FileViewer } from "./file-viewer";

/** A cited file: the base it is in, and the name the citation gave it. */
export interface CitedFile {
  kbId: string;
  filename: string;
}

/**
 * The original of a file a search result or an answer cited, opened.
 *
 * A citation names a file, not a document row, so this finds the row by name and
 * opens the knowledge base's own viewer on it - the same dialog, with the same
 * parsed tab, as opening it from the base's page. A file the base no longer holds
 * says so rather than opening an empty viewer.
 */
export function SourceViewer({ cited, onClose }: { cited: CitedFile; onClose: () => void }) {
  const t = useTranslations("kb");
  const tCommon = useTranslations("common");
  const found = useQuery({
    queryKey: qk.kb.documentNamed(cited.kbId, cited.filename),
    queryFn: () => findKBDocument(cited.kbId, cited.filename),
    retry: false,
  });

  if (found.isPending) return null;
  if (found.data) return <FileViewer kbId={cited.kbId} doc={found.data} open onClose={onClose} />;

  return (
    <Dialog open onOpenChange={onClose}>
      <DialogContent className={DIALOG_CONFIRM}>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <FileX className="text-muted-foreground h-4 w-4" aria-hidden />
            {cited.filename}
          </DialogTitle>
          <DialogDescription>{t("citedFileGone")}</DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onClose}>
            {tCommon("close")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
