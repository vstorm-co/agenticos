"use client";

import { Code2, Globe, Link2, Plug } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui";
import { DOCS } from "@/lib/constants";
import type { EmbedKind } from "@/types/embeds";

/**
 * What a caller picked. `api` is the one choice that creates nothing.
 *
 * The public API needs a credential the organization already has and no
 * per-agent object at all, so it is a card here for the reason the other three
 * are: this panel answers "where can people reach this agent", and an answer
 * left off the list is an answer nobody finds.
 */
export type SurfaceChoice = EmbedKind | "api";

interface Surface {
  choice: SurfaceChoice;
  Icon: typeof Globe;
  titleKey: string;
  bodyKey: string;
}

/**
 * The four public surfaces, as four cards.
 *
 * They used to be one button - *Publish as widget* - with the socket URL and the
 * hosted page behind it, which is how somebody looking for either found neither.
 * A widget, a socket and a page differ in what there is to configure, so the
 * choice is made before the form rather than discovered inside it.
 */
const SURFACES: readonly Surface[] = [
  { choice: "widget", Icon: Globe, titleKey: "surfaceWidget", bodyKey: "surfaceWidgetBody" },
  { choice: "page", Icon: Link2, titleKey: "surfacePage", bodyKey: "surfacePageBody" },
  { choice: "socket", Icon: Plug, titleKey: "surfaceSocket", bodyKey: "surfaceSocketBody" },
  { choice: "api", Icon: Code2, titleKey: "surfaceApi", bodyKey: "surfaceApiBody" },
] as const;

export function SurfacePicker({ onPick }: { onPick: (choice: SurfaceChoice) => void }) {
  const t = useTranslations("agents");

  return (
    <div className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-2">
        {SURFACES.map(({ choice, Icon, titleKey, bodyKey }) => (
          <button
            key={choice}
            type="button"
            onClick={() => onPick(choice)}
            className="border-border hover:border-primary hover:bg-accent/40 rounded-lg border p-3 text-left transition-colors"
          >
            <span className="flex items-center gap-2 text-sm font-medium">
              <Icon className="h-4 w-4 shrink-0" />
              {t(titleKey)}
            </span>
            <span className="text-muted-foreground mt-1 block text-xs">{t(bodyKey)}</span>
          </button>
        ))}
      </div>
      <p className="text-muted-foreground text-xs">{t("surfaceDashboardAlways")}</p>
    </div>
  );
}

/**
 * The public API, which is a credential and a request rather than an object.
 *
 * Shown where the other three surfaces are configured, and it says plainly that
 * there is nothing to configure - the alternative is a card that opens an empty
 * form and leaves somebody looking for the setting it does not have.
 */
export function ApiSurfaceNotes({ agentId, onClose }: { agentId: string; onClose: () => void }) {
  const t = useTranslations("agents");
  const tc = useTranslations("common");

  return (
    <div className="border-border space-y-3 rounded-lg border border-dashed p-4">
      <p className="text-sm font-medium">{t("surfaceApi")}</p>
      <p className="text-muted-foreground text-xs">{t("surfaceApiNotes")}</p>
      <code className="bg-muted block overflow-x-auto rounded-md p-2 font-mono text-xs whitespace-pre">
        {`curl -X POST "$AGENTICOS_URL/api/v1/agents/${agentId}/runs" \\\n  -H "X-API-Key: $AGENTICOS_API_KEY" \\\n  -d '{"message": "hello"}'`}
      </code>
      <div className="flex items-center gap-2">
        <Button variant="ghost" size="sm" onClick={onClose}>
          {tc("close")}
        </Button>
        <a
          className="text-muted-foreground hover:text-foreground text-xs underline"
          href={DOCS.PUBLIC_API}
          target="_blank"
          rel="noreferrer"
        >
          {t("surfaceApiDocs")}
        </a>
      </div>
    </div>
  );
}
