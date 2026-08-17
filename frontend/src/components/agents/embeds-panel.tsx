"use client";

import { useState } from "react";
import { Check, Code2, Copy, Pencil, Radio, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { EmbedForm } from "@/components/agents/embed-form";
import {
  ApiSurfaceNotes,
  SurfacePicker,
  type SurfaceChoice,
} from "@/components/agents/surface-picker";
import { LoadingState } from "@/components/states";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  ConfirmDialog,
  Switch,
} from "@/components/ui";
import { useEmbeds } from "@/hooks";
import { useCopyToClipboard } from "@/hooks/use-copy-to-clipboard";
import { DOCS } from "@/lib/constants";
import { cn } from "@/lib/utils";
import type { Embed, EmbedKind } from "@/types/embeds";

interface EmbedsPanelProps {
  agentId: string;
  /** `agents:publish` on this agent - the same permission an exposure needs. */
  canManage: boolean;
}

/** What each surface is called, so a row says what it is without reading its URL. */
const KIND_LABEL: Record<EmbedKind, string> = {
  widget: "surfaceWidget",
  socket: "surfaceSocket",
  page: "surfacePage",
};

/**
 * The public surfaces this agent is published on.
 *
 * A list and a picker, rather than one *Publish as widget* button with the other
 * two surfaces hidden inside its form. They are one table underneath - one
 * public key, one rate bucket, one budget, one pause switch - and three
 * different things to configure, which is exactly the shape a picker models and
 * a single form does not.
 */
export function EmbedsPanel({ agentId, canManage }: EmbedsPanelProps) {
  const t = useTranslations("agents");
  const tc = useTranslations("common");
  const { embeds, isLoading, create, update, remove, uploadLogo } = useEmbeds(agentId);
  const [picked, setPicked] = useState<SurfaceChoice | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<Embed | null>(null);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Radio className="h-4 w-4" />
          {t("publicSurfaces")}
        </CardTitle>
        <CardDescription>{t("publicSurfacesDescription")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {isLoading ? (
          <LoadingState variant="skeleton-panel" rows={1} />
        ) : embeds.length === 0 ? (
          <p className="text-muted-foreground text-sm">{t("notPublishedAnySite")}</p>
        ) : (
          <div className="space-y-3">
            {embeds.map((embed) =>
              editing === embed.id ? (
                // In place of its row rather than below the list: the row is
                // what somebody clicked, and a form that opens somewhere else
                // makes "which one am I editing" a question.
                <EmbedForm
                  key={embed.id}
                  agentId={agentId}
                  kind={embed.kind}
                  embed={embed}
                  pending={update.isPending || uploadLogo.isPending}
                  onUploadLogo={(file) => uploadLogo.mutate({ id: embed.id, file })}
                  onSubmit={({ agent_id: _agent, ...changes }) =>
                    update.mutate(
                      { id: embed.id, ...changes },
                      { onSuccess: () => setEditing(null) },
                    )
                  }
                  onCancel={() => setEditing(null)}
                />
              ) : (
                <EmbedRow
                  key={embed.id}
                  embed={embed}
                  canManage={canManage}
                  onToggle={(active) => update.mutate({ id: embed.id, is_active: active })}
                  onEdit={() => {
                    setPicked(null);
                    setEditing(embed.id);
                  }}
                  onDelete={() => setPendingDelete(embed)}
                />
              ),
            )}
          </div>
        )}

        {picked === "api" && <ApiSurfaceNotes agentId={agentId} onClose={() => setPicked(null)} />}
        {picked !== null && picked !== "api" && (
          <EmbedForm
            agentId={agentId}
            kind={picked}
            pending={create.isPending}
            onSubmit={(embed) => create.mutate(embed, { onSuccess: () => setPicked(null) })}
            onCancel={() => setPicked(null)}
          />
        )}
        {canManage && picked === null && editing === null && <SurfacePicker onPick={setPicked} />}
      </CardContent>

      {pendingDelete !== null && (
        <ConfirmDialog
          open
          onOpenChange={() => setPendingDelete(null)}
          title={tc("removeNamedConfirm", { name: pendingDelete.name })}
          description={t("everyPageCarryingIts")}
          confirmLabel={t("remove")}
          destructive
          loading={remove.isPending}
          onConfirm={async () => {
            await remove.mutateAsync(pendingDelete.id);
            setPendingDelete(null);
          }}
        />
      )}
    </Card>
  );
}

/**
 * One thing a customer copies, labelled with what it is for.
 *
 * A component rather than two blocks inline because each copy button owns its
 * own `copied` state: one hook shared between them ticks both, which reads as
 * having copied the socket URL when the snippet went to the clipboard.
 */
function Integration({
  label,
  value,
  copyLabel,
}: {
  label: string;
  value: string;
  copyLabel: string;
}) {
  const { copy, copied } = useCopyToClipboard();

  return (
    <div className="mt-3">
      <p className="text-muted-foreground mb-1 text-xs font-medium">{label}</p>
      <div className="flex items-start gap-2">
        <code className="bg-muted min-w-0 flex-1 overflow-x-auto rounded-md p-2 font-mono text-xs whitespace-pre">
          {value}
        </code>
        <Button variant="outline" size="sm" onClick={() => copy(value)} aria-label={copyLabel}>
          {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
        </Button>
      </div>
    </div>
  );
}

function EmbedRow({
  embed,
  canManage,
  onToggle,
  onEdit,
  onDelete,
}: {
  embed: Embed;
  canManage: boolean;
  onToggle: (active: boolean) => void;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const t = useTranslations("agents");
  const tc = useTranslations("common");

  return (
    <div className="border-border rounded-lg border p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium">{embed.name}</span>
        <Badge variant="secondary">{t(KIND_LABEL[embed.kind])}</Badge>
        {embed.auth_mode === "jwt" && <Badge variant="outline">{t("authSignedIn")}</Badge>}
        {!embed.is_active && <Badge variant="outline">{t("paused")}</Badge>}
        <div className="flex-1" />
        {canManage && (
          <>
            <Switch
              checked={embed.is_active}
              onCheckedChange={onToggle}
              aria-label={`${embed.is_active ? t("pause") : t("resume")} ${embed.name}`}
            />
            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8"
              onClick={onEdit}
              aria-label={t("editSurface", { name: embed.name })}
            >
              <Pencil className="h-4 w-4" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className="text-destructive hover:text-destructive h-8 w-8"
              onClick={onDelete}
              aria-label={tc("removeNamed", { name: embed.name })}
            >
              <Trash2 className="h-4 w-4" />
            </Button>
          </>
        )}
      </div>

      {embed.snippet !== null && (
        <Integration
          label={t("scriptTagIntegration")}
          value={embed.snippet}
          copyLabel={t("copySnippet")}
        />
      )}
      {embed.socket_url !== null && (
        <Integration
          label={t("socketIntegration")}
          value={embed.socket_url}
          copyLabel={t("copySocketUrl")}
        />
      )}
      {embed.page_url !== null && (
        <>
          <Integration
            label={t("hostedIntegration")}
            value={embed.page_url}
            copyLabel={t("copyHostedUrl")}
          />
          <p className="text-muted-foreground mt-2 text-xs">{t("hostedLinkProtection")}</p>
        </>
      )}

      {embed.socket_url !== null && (
        <p className="text-muted-foreground mt-2 text-xs">
          {t("nativeClientOriginNote")}{" "}
          <a
            href={DOCS.RAW_WEBSOCKET}
            target="_blank"
            rel="noopener noreferrer"
            className="underline underline-offset-2"
          >
            {t("socketFramesAndCloseCodes")}
          </a>
        </p>
      )}

      {embed.kind !== "page" && (
        <p className="text-muted-foreground mt-2 flex items-center gap-1.5 text-xs">
          <Code2 className="h-3 w-3 shrink-0" />
          <span
            className={cn("truncate", embed.allowed_origins.length === 0 && "text-destructive")}
          >
            {embed.allowed_origins.length === 0
              ? t("noSitesAllowedWidget")
              : embed.allowed_origins.join(", ")}
          </span>
        </p>
      )}
    </div>
  );
}
