"use client";

import { AlertCircle, CheckCircle2, Clock, Loader2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui";
import { cn } from "@/lib/utils";
import type { KBDocument } from "@/types";

/**
 * What actually read one document, and whether that was the collection's doing.
 *
 * `was_overridden` is the answer to a question asked long after the fact, so it
 * is worth a badge rather than a tooltip: the collection's settings move on, and
 * a document parsed under the old ones looks identical to one somebody chose to
 * parse differently.
 *
 * A document ingested before any of this was recorded says so, rather than
 * naming the collection's current parser - which would be a guess, and the kind
 * that is impossible to catch.
 */
export function DocumentProvenance({ doc }: { doc: KBDocument }) {
  const t = useTranslations("pages.kb");
  if (doc.parser === null) {
    return <span className="text-muted-foreground text-xs">{t("notRecorded")}</span>;
  }
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span
        className="text-muted-foreground font-mono text-xs"
        title={
          doc.embedding_model === null
            ? undefined
            : t("embeddedWith", { model: doc.embedding_model })
        }
      >
        {doc.parser}
      </span>
      {doc.image_description_model !== null && (
        <span
          className="text-muted-foreground text-xs"
          title={t("imagesDescribedBy", { model: doc.image_description_model })}
        >
          {t("images")}
        </span>
      )}
      {doc.was_overridden && <Badge variant="secondary">{t("overridden")}</Badge>}
    </div>
  );
}

export function DocumentStatusBadge({
  status,
  message,
}: {
  status: string;
  message: string | null;
}) {
  const t = useTranslations("pages.kb");
  // Four one-word labels, which is under `check_i18n.py`'s two-word threshold -
  // so they sat here in English and rendered that way under every locale. The
  // fall-through keeps the server's own word for a status this build does not
  // know: a value nothing has translated, rather than copy somebody wrote.
  const config = {
    completed: { Icon: CheckCircle2, label: t("statusReady"), spin: false },
    processing: { Icon: Loader2, label: t("statusProcessing"), spin: true },
    pending: { Icon: Clock, label: t("statusPending"), spin: false },
    failed: { Icon: AlertCircle, label: t("statusFailed"), spin: false },
  } as const;
  const c = (config as Record<string, (typeof config)[keyof typeof config]>)[status] ?? {
    Icon: Clock,
    label: status,
    spin: false,
  };
  return (
    <Badge
      variant="outline"
      title={message ?? undefined}
      className={cn(
        "border-border gap-1 font-normal",
        status === "failed" ? "text-destructive" : "text-muted-foreground",
      )}
    >
      <c.Icon className={cn("h-3 w-3", c.spin && "animate-spin")} />
      {c.label}
    </Badge>
  );
}
