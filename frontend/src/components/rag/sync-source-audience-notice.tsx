"use client";

import { Eye } from "lucide-react";
import { useTranslations } from "next-intl";

import type { KBScope } from "@/types/knowledge-base";

/** One message per scope, because each names a different set of people. */
const AUDIENCE = {
  personal: "audiencePersonal",
  org: "audienceOrg",
  app: "audienceApp",
} as const satisfies Record<KBScope, string>;

/**
 * Who will be able to search what this source ingests.
 *
 * Access is decided at the **collection** and there is no per-document isolation
 * inside one, so everything the credential can reach becomes readable by
 * everyone who can read the collection it is filed under
 * (`docs/file-processing.md#who-may-reach-a-collection`). The platform
 * deliberately does not mirror a source's own ACLs - a Drive file's sharing, a
 * Confluence space's restrictions - because a mirrored ACL goes stale between
 * syncs and stale authorization is worse than none.
 *
 * That makes the decision the operator's, which was already true; what was wrong
 * is that the wizard made it **silently**. A Confluence token issued for a whole
 * instance, pointed at an `org` collection, published the instance to every
 * member holding `collections:view` and nothing on any step said so (#982).
 *
 * The credential is named as well as the audience, because the pair is the
 * decision: the credential's own permissions are a ceiling nothing in this
 * product can raise, while `config` narrows the reach and cannot be relied on to
 * keep it narrow - it is a field anyone with `collections:edit` can widen later.
 */
export function SourceAudienceNotice({
  scope,
  collectionName,
  credentialName,
}: {
  /** The collection's scope, or `undefined` for a source filed under none. */
  scope?: KBScope;
  collectionName?: string;
  /**
   * The chosen vault credential. Absent when this caller cannot read the vault,
   * or before one has been picked - the sentence then says "the credential this
   * source uses" rather than naming it, because a message with an empty
   * parameter in it is worse than one that never promised a name.
   */
  credentialName?: string;
}) {
  const t = useTranslations("rag");

  return (
    <div className="border-foreground/10 bg-foreground/[0.03] mt-5 rounded-xl border p-4">
      <p className="text-foreground/80 flex items-center gap-2 text-xs font-medium tracking-wider uppercase">
        <Eye className="h-3.5 w-3.5" aria-hidden />
        {t("audienceTitle")}
      </p>
      <p className="text-foreground/70 mt-2 text-sm">
        {scope === undefined || collectionName === undefined
          ? t("audienceUnassigned")
          : t(AUDIENCE[scope], {
              named: credentialName === undefined ? "no" : "yes",
              credential: credentialName ?? "",
              collection: collectionName,
            })}
      </p>
    </div>
  );
}
