"use client";

import { Eye } from "lucide-react";
import { useTranslations } from "next-intl";

import { useSecrets } from "@/hooks";
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
 *
 * **The vault is read here rather than by the wizard.** This renders inside the
 * dialog, so the query starts when a reader is actually looking at the sentence;
 * the same call in the wizard's own body ran on every load of the knowledge-base
 * page, dialog shut, including for members who hold no `secrets:view` and get a
 * refusal for it.
 */
export function SourceAudienceNotice({
  scope,
  collectionName,
  secretId,
  needsCredential,
}: {
  /** The collection's scope, or `undefined` for a source filed under none. */
  scope?: KBScope;
  collectionName?: string;
  /** Which vault credential the source will authenticate with, if it has one. */
  secretId?: string | null;
  /**
   * Whether this connector authenticates at all. A connector declaring
   * `secret_kind: "none"` - a public crawler - has none to name, and a sentence
   * about "the credential this source uses" would contradict the step before it.
   */
  needsCredential: boolean;
}) {
  const t = useTranslations("rag");
  const { secrets } = useSecrets();
  const credential = secrets.find((secret) => secret.id === secretId)?.name;

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
              // Three states, not two: no credential to name, one this caller
              // cannot read the name of, and one it can.
              credentialing: !needsCredential
                ? "none"
                : credential === undefined
                  ? "unknown"
                  : "named",
              credential: credential ?? "",
              collection: collectionName,
            })}
      </p>
    </div>
  );
}
