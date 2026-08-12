"use client";

import { useState } from "react";
import { Check, Code2, Copy, Globe, Plus, Trash2 } from "lucide-react";

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
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Switch,
  MarkdownEditor,
  Textarea,
} from "@/components/ui";
import { useEmbeds } from "@/hooks";
import { useCopyToClipboard } from "@/hooks/use-copy-to-clipboard";
import { DOCS } from "@/lib/constants";
import { cn } from "@/lib/utils";
import {
  DEFAULT_EMBED_THEME,
  type Embed,
  type EmbedAuthMode,
  type EmbedVariable,
} from "@/types/embeds";
import { EmbedVariables } from "@/components/agents/embed-variables";
import { useTranslations } from "next-intl";

interface EmbedsPanelProps {
  agentId: string;
  /** `agents:publish` on this agent - the same permission an exposure needs. */
  canManage: boolean;
}

/** Origins as typed: one per line, blank lines dropped, whitespace trimmed. */
function parseOrigins(value: string): string[] {
  return value
    .split(/[\n,]/)
    .map((line) => line.trim())
    .filter(Boolean);
}

/**
 * The widgets this agent is published as.
 *
 * The panel leads with the snippet rather than the settings, because pasting it
 * is the only step a customer actually performs; everything else is ours to get
 * right beforehand.
 *
 * The origin field is a textarea and not a nicety: an empty allow-list allows
 * nothing, and that has to be visible at the moment somebody creates a widget
 * rather than discovered when it silently refuses to open.
 */
export function EmbedsPanel({ agentId, canManage }: EmbedsPanelProps) {
  const t = useTranslations("agents");
  const tc = useTranslations("common");
  const { embeds, isLoading, create, update, remove } = useEmbeds(agentId);
  const [creating, setCreating] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<Embed | null>(null);

  const [name, setName] = useState(t("websiteWidget"));
  const [origins, setOrigins] = useState("");
  const [authMode, setAuthMode] = useState<EmbedAuthMode>("public");
  const [secret, setSecret] = useState("");
  const [context, setContext] = useState("");
  const [variables, setVariables] = useState<EmbedVariable[]>([]);
  const [accent, setAccent] = useState(DEFAULT_EMBED_THEME.accent);

  const reset = () => {
    setCreating(false);
    setName(t("websiteWidget2"));
    setOrigins("");
    setAuthMode("public");
    setSecret("");
    setContext("");
    setVariables([]);
    setAccent(DEFAULT_EMBED_THEME.accent);
  };

  const submit = () => {
    create.mutate(
      {
        agent_id: agentId,
        name: name.trim(),
        auth_mode: authMode,
        jwt_secret: authMode === "jwt" ? secret : null,
        allowed_origins: parseOrigins(origins),
        theme: { ...DEFAULT_EMBED_THEME, accent },
        context: context.trim() || null,
        // A row somebody started and left blank is not a declaration. Dropped
        // here rather than refused on save: the name is the contract, and an
        // empty one has nothing to contract about.
        context_variables: variables.filter((variable) => variable.name.trim() !== ""),
        rate_limit_per_minute: 10,
      },
      { onSuccess: reset },
    );
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Globe className="h-4 w-4" />
          {t("websiteWidget")}
        </CardTitle>
        <CardDescription>{t("publishAgentAsChat")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {isLoading ? (
          <LoadingState variant="skeleton-panel" rows={1} />
        ) : embeds.length === 0 && !creating ? (
          <p className="text-muted-foreground text-sm">{t("notPublishedAnySite")}</p>
        ) : (
          <div className="space-y-3">
            {embeds.map((embed) => (
              <EmbedRow
                key={embed.id}
                embed={embed}
                canManage={canManage}
                onToggle={(active) => update.mutate({ id: embed.id, is_active: active })}
                onDelete={() => setPendingDelete(embed)}
              />
            ))}
          </div>
        )}

        {creating && (
          <div className="border-border space-y-4 rounded-lg border border-dashed p-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="embed-name">{t("name5")}</Label>
                <Input
                  id="embed-name"
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  placeholder={t("websiteWidget")}
                />
                <p className="text-muted-foreground text-xs">{t("youNotVisitorsWhich")}</p>
              </div>
              <div className="space-y-2">
                <Label htmlFor="embed-accent">{t("accentColour")}</Label>
                <div className="flex items-center gap-2">
                  <input
                    id="embed-accent"
                    type="color"
                    value={accent}
                    onChange={(event) => setAccent(event.target.value)}
                    className="border-input h-9 w-12 cursor-pointer rounded-md border bg-transparent"
                  />
                  <Input
                    value={accent}
                    onChange={(event) => setAccent(event.target.value)}
                    className="font-mono"
                  />
                </div>
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="embed-origins">{t("allowedSites")}</Label>
              <Textarea
                id="embed-origins"
                value={origins}
                onChange={(event) => setOrigins(event.target.value)}
                placeholder={"https://acme.com\nhttps://www.acme.com"}
                rows={3}
                className="font-mono text-sm"
              />
              <p className="text-muted-foreground text-xs">{t("onePerLineDifferent")}</p>
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="embed-auth">{t("whoCanUse")}</Label>
                <Select
                  value={authMode}
                  onValueChange={(value) => setAuthMode(value as EmbedAuthMode)}
                >
                  <SelectTrigger id="embed-auth">
                    <SelectValue />
                  </SelectTrigger>
                  {/* Each option's second line exists to tell it from the other
                      one, so it belongs in `trailing`: an item's `ItemText` is
                      what Radix draws in the closed trigger, where the sentence
                      distinguishing two modes is left describing one.

                      The cap is what that costs. Stacked, the two lines were
                      about 30 characters wide; side by side they are one row of
                      about 60, and a popper sized to `max-content` overflowed a
                      narrow viewport. `runtime-field.tsx` caps its content for
                      the same reason. */}
                  <SelectContent className="max-w-[min(26rem,90vw)]">
                    <SelectItem
                      value="public"
                      trailing={
                        <span className="text-muted-foreground ml-auto max-w-64 pl-3 text-xs">
                          {t("noSignMarketingPage")}
                        </span>
                      }
                    >
                      {t("anyoneThoseSites")}
                    </SelectItem>
                    <SelectItem
                      value="jwt"
                      trailing={
                        <span className="text-muted-foreground ml-auto max-w-64 pl-3 text-xs">
                          {t("yourBackendSignsToken")}
                        </span>
                      }
                    >
                      {t("signedUsersOnly")}
                    </SelectItem>
                  </SelectContent>
                </Select>
              </div>
              {authMode === "jwt" && (
                <div className="space-y-2">
                  <Label htmlFor="embed-secret">{t("signingSecret2")}</Label>
                  <Input
                    id="embed-secret"
                    value={secret}
                    onChange={(event) => setSecret(event.target.value)}
                    placeholder={t("atLeast16Characters")}
                    className="font-mono"
                  />
                  <p className="text-muted-foreground text-xs">{t("storedVaultNeverShown")}</p>
                </div>
              )}
            </div>

            <div className="space-y-2">
              <Label htmlFor="embed-context">{t("contextPlacement")}</Label>
              <MarkdownEditor
                id="embed-context"
                value={context}
                onChange={setContext}
                label={t("contextPlacement")}
                placeholder={t("youArePricingPage")}
                rows={6}
                disabled={create.isPending}
              />
              <p className="text-muted-foreground text-xs">{t("addedFirstMessageEach")}</p>
            </div>

            <EmbedVariables
              variables={variables}
              disabled={create.isPending}
              onChange={setVariables}
            />

            <div className="flex items-center gap-2">
              <Button
                onClick={submit}
                disabled={create.isPending || !name.trim() || parseOrigins(origins).length === 0}
              >
                {t("publishWidget")}
              </Button>
              <Button variant="ghost" onClick={reset}>
                {t("cancel3")}
              </Button>
              {parseOrigins(origins).length === 0 && (
                <span className="text-muted-foreground text-xs">{t("addAtLeastOne")}</span>
              )}
            </div>
          </div>
        )}

        {canManage && !creating && (
          <Button variant="outline" onClick={() => setCreating(true)}>
            <Plus className="h-4 w-4" />
            {t("publishAsWidget")}
          </Button>
        )}
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
  onDelete,
}: {
  embed: Embed;
  canManage: boolean;
  onToggle: (active: boolean) => void;
  onDelete: () => void;
}) {
  const t = useTranslations("agents");
  const tc = useTranslations("common");

  return (
    <div className="border-border rounded-lg border p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium">{embed.name}</span>
        <Badge variant={embed.auth_mode === "jwt" ? "secondary" : "outline"}>
          {embed.auth_mode === "jwt" ? "signed-in users" : "public"}
        </Badge>
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
              className="text-destructive hover:text-destructive h-8 w-8"
              onClick={onDelete}
              aria-label={tc("removeNamed", { name: embed.name })}
            >
              <Trash2 className="h-4 w-4" />
            </Button>
          </>
        )}
      </div>

      <Integration
        label={t("scriptTagIntegration")}
        value={embed.snippet}
        copyLabel={t("copySnippet")}
      />
      <Integration
        label={t("socketIntegration")}
        value={embed.socket_url}
        copyLabel={t("copySocketUrl")}
      />

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

      <p className="text-muted-foreground mt-2 flex items-center gap-1.5 text-xs">
        <Code2 className="h-3 w-3 shrink-0" />
        <span className={cn("truncate", embed.allowed_origins.length === 0 && "text-destructive")}>
          {embed.allowed_origins.length === 0
            ? t("noSitesAllowedWidget")
            : embed.allowed_origins.join(", ")}
        </span>
      </p>
    </div>
  );
}
