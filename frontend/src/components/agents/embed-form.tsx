"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { EmbedVariables } from "@/components/agents/embed-variables";
import { PageFields } from "@/components/agents/page-fields";
import { WidgetFields } from "@/components/agents/widget-fields";
import {
  Button,
  Input,
  Label,
  MarkdownEditor,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Textarea,
} from "@/components/ui";
import {
  defaultConfigFor,
  type Embed,
  type EmbedAuthMode,
  type EmbedConfig,
  type EmbedKind,
  type EmbedVariable,
  type NewEmbed,
} from "@/types/embeds";

const MIN_SECRET = 16;

/** What a new embed is called until somebody renames it, keyed per surface. */
const NAME_KEY: Record<EmbedKind, string> = {
  widget: "surfaceWidget",
  socket: "surfaceSocket",
  page: "surfacePage",
};

/** Origins as typed: one per line or comma-separated, blank entries dropped. */
export function parseOrigins(value: string): string[] {
  return value
    .split(/[\n,]/)
    .map((line) => line.trim())
    .filter(Boolean);
}

/**
 * One agent on one surface: publishing it, and editing what was published.
 *
 * The kind is chosen before this form opens and is never editable in it, which
 * is the rule the backend holds too: a tag already pasted, a client already
 * written and a link already sent all name one row, so changing what it is would
 * change what all three do without touching any of them. Everything else about
 * a live surface is editable in place - a colour, a welcome, one more allowed
 * site - because the alternative is deleting it, and its key does not come back.
 *
 * Three of the fields are conditional, and each because the surface makes it
 * meaningless rather than merely unusual. Allowed origins are what admit a
 * widget or a socket and have nothing to say about a page we serve, which is why
 * a page can be published without naming a single site - the whole point of the
 * link. Token auth is refused on a page, because the token would travel in the
 * URL. And what there is to style is a bubble, a page, or nothing at all.
 */
export function EmbedForm({
  agentId,
  kind,
  embed,
  pending,
  onSubmit,
  onUploadLogo,
  onCancel,
}: {
  agentId: string;
  kind: EmbedKind;
  /** The row being edited. Absent when publishing a new surface. */
  embed?: Embed;
  pending: boolean;
  onSubmit: (embed: NewEmbed) => void;
  /** Only wired on an existing row - an upload needs somewhere to go. */
  onUploadLogo?: (file: File) => void;
  onCancel: () => void;
}) {
  const t = useTranslations("agents");
  const needsOrigins = kind !== "page";

  const [name, setName] = useState(embed?.name ?? t(NAME_KEY[kind]));
  const [config, setConfig] = useState<EmbedConfig>(embed?.config ?? defaultConfigFor(kind));
  const [origins, setOrigins] = useState((embed?.allowed_origins ?? []).join("\n"));
  const [authMode, setAuthMode] = useState<EmbedAuthMode>(embed?.auth_mode ?? "public");
  const [secret, setSecret] = useState("");
  const [context, setContext] = useState(embed?.context ?? "");
  const [variables, setVariables] = useState<EmbedVariable[]>(embed?.context_variables ?? []);

  const originList = parseOrigins(origins);
  const missingOrigins = needsOrigins && originList.length === 0;
  // Blank is allowed only where the stored secret still verifies what it always
  // did: the same embed, already in token mode. Switching *into* token mode
  // without one would leave the surface checking against whatever was there
  // before, which the backend refuses and this must not offer.
  const keepsStoredSecret = authMode === "jwt" && embed?.auth_mode === "jwt" && secret === "";
  const missingSecret =
    authMode === "jwt" && !keepsStoredSecret && secret.trim().length < MIN_SECRET;

  return (
    <div className="border-border space-y-4 rounded-lg border border-dashed p-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-2">
          <Label htmlFor="embed-name">{t("name5")}</Label>
          <Input
            id="embed-name"
            value={name}
            disabled={pending}
            onChange={(event) => setName(event.target.value)}
          />
          <p className="text-muted-foreground text-xs">{t("youNotVisitorsWhich")}</p>
        </div>
      </div>

      {config.kind === "widget" && (
        <WidgetFields config={config} disabled={pending} onChange={setConfig} />
      )}

      {needsOrigins && (
        <div className="space-y-2">
          <Label htmlFor="embed-origins">{t("allowedSites")}</Label>
          <Textarea
            id="embed-origins"
            value={origins}
            disabled={pending}
            onChange={(event) => setOrigins(event.target.value)}
            placeholder={"https://acme.com\nhttps://www.acme.com"}
            rows={3}
            className="font-mono text-sm"
          />
          <p className="text-muted-foreground text-xs">
            {kind === "socket" ? t("originsSocketHint") : t("onePerLineDifferent")}
          </p>
        </div>
      )}

      {needsOrigins && (
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="embed-auth">{t("whoCanUse")}</Label>
            <Select value={authMode} onValueChange={(value) => setAuthMode(value as EmbedAuthMode)}>
              <SelectTrigger id="embed-auth">
                <SelectValue />
              </SelectTrigger>
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
                disabled={pending}
                onChange={(event) => setSecret(event.target.value)}
                placeholder={
                  embed?.has_jwt_secret ? t("secretUnchanged") : t("atLeast16Characters")
                }
                className="font-mono"
              />
              <p className="text-muted-foreground text-xs">{t("storedVaultNeverShown")}</p>
            </div>
          )}
        </div>
      )}

      {config.kind === "page" && (
        <PageFields
          config={config}
          variables={variables}
          disabled={pending}
          hasCustomLogo={embed?.has_custom_logo ?? false}
          onUpload={embed && onUploadLogo ? onUploadLogo : undefined}
          onChange={setConfig}
        />
      )}

      <div className="space-y-2">
        <Label htmlFor="embed-context">{t("contextPlacement")}</Label>
        <MarkdownEditor
          id="embed-context"
          value={context}
          onChange={setContext}
          label={t("contextPlacement")}
          placeholder={t("youArePricingPage")}
          rows={6}
          disabled={pending}
        />
        <p className="text-muted-foreground text-xs">{t("addedFirstMessageEach")}</p>
      </div>

      <EmbedVariables
        variables={variables}
        disabled={pending}
        kind={kind}
        onChange={setVariables}
      />

      <div className="flex flex-wrap items-center gap-2">
        <Button
          disabled={pending || !name.trim() || missingOrigins || missingSecret}
          onClick={() =>
            onSubmit({
              agent_id: agentId,
              name: name.trim(),
              config,
              auth_mode: authMode,
              jwt_secret: authMode === "jwt" && !keepsStoredSecret ? secret : null,
              allowed_origins: originList,
              context: context.trim() || null,
              // A row somebody started and left blank is not a declaration.
              // Dropped here rather than refused on save: the name is the
              // contract, and an empty one has nothing to contract about.
              context_variables: variables.filter((variable) => variable.name.trim() !== ""),
              // Carried through on edit rather than reset: there is no field for
              // it in this form, so a limit set through the API to anything but
              // the default would otherwise be rewritten to 10 by every save.
              rate_limit_per_minute: embed?.rate_limit_per_minute ?? 10,
            })
          }
        >
          {embed ? t("saveSurface") : t("publishSurface")}
        </Button>
        <Button variant="ghost" disabled={pending} onClick={onCancel}>
          {t("cancel3")}
        </Button>
        {missingOrigins && (
          <span className="text-muted-foreground text-xs">{t("addAtLeastOne")}</span>
        )}
      </div>
    </div>
  );
}
