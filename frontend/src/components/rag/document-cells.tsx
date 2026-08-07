"use client";

import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui";
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
