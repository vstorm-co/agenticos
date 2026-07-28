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
  Textarea,
} from "@/components/ui";
import { useEmbeds } from "@/hooks";
import { useCopyToClipboard } from "@/hooks/use-copy-to-clipboard";
import { cn } from "@/lib/utils";
import { DEFAULT_EMBED_THEME, type Embed, type EmbedAuthMode } from "@/types/embeds";

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
  const { embeds, isLoading, create, update, remove } = useEmbeds(agentId);
  const [creating, setCreating] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<Embed | null>(null);

  const [name, setName] = useState("Website widget");
  const [origins, setOrigins] = useState("");
  const [authMode, setAuthMode] = useState<EmbedAuthMode>("public");
  const [secret, setSecret] = useState("");
  const [context, setContext] = useState("");
  const [accent, setAccent] = useState(DEFAULT_EMBED_THEME.accent);

  const reset = () => {
    setCreating(false);
    setName("Website widget");
    setOrigins("");
    setAuthMode("public");
    setSecret("");
    setContext("");
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
          Website widget
        </CardTitle>
        <CardDescription>
          Publish this agent as a chat widget for a site you do not control - one script tag, no
          build step. The key in that tag is public, so what actually protects the agent is the list
          of sites it may be opened from. An empty list allows nothing.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {isLoading ? (
          <LoadingState variant="skeleton-panel" rows={1} />
        ) : embeds.length === 0 && !creating ? (
          <p className="text-muted-foreground text-sm">Not published to any site yet.</p>
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
                <Label htmlFor="embed-name">Name</Label>
                <Input
                  id="embed-name"
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  placeholder="Website widget"
                />
                <p className="text-muted-foreground text-xs">
                  For you, not for visitors - which placement this is.
                </p>
              </div>
              <div className="space-y-2">
                <Label htmlFor="embed-accent">Accent colour</Label>
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
              <Label htmlFor="embed-origins">Allowed sites</Label>
              <Textarea
                id="embed-origins"
                value={origins}
                onChange={(event) => setOrigins(event.target.value)}
                placeholder={"https://acme.com\nhttps://www.acme.com"}
                rows={3}
                className="font-mono text-sm"
              />
              <p className="text-muted-foreground text-xs">
                One per line. A different port or subdomain is a different site - the browser treats
                them as such, so this list has to.
              </p>
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="embed-auth">Who can use it</Label>
                <Select
                  value={authMode}
                  onValueChange={(value) => setAuthMode(value as EmbedAuthMode)}
                >
                  <SelectTrigger id="embed-auth">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="public">
                      <span className="flex flex-col">
                        <span>Anyone on those sites</span>
                        <span className="text-muted-foreground text-xs">
                          No sign-in - a marketing page
                        </span>
                      </span>
                    </SelectItem>
                    <SelectItem value="jwt">
                      <span className="flex flex-col">
                        <span>Signed-in users only</span>
                        <span className="text-muted-foreground text-xs">
                          Your backend signs a token we verify
                        </span>
                      </span>
                    </SelectItem>
                  </SelectContent>
                </Select>
              </div>
              {authMode === "jwt" && (
                <div className="space-y-2">
                  <Label htmlFor="embed-secret">Signing secret</Label>
                  <Input
                    id="embed-secret"
                    value={secret}
                    onChange={(event) => setSecret(event.target.value)}
                    placeholder="At least 16 characters"
                    className="font-mono"
                  />
                  <p className="text-muted-foreground text-xs">
                    Stored in the vault and never shown again. Your backend signs each visitor a
                    HS256 token with it.
                  </p>
                </div>
              )}
            </div>

            <div className="space-y-2">
              <Label htmlFor="embed-context">Context for this placement</Label>
              <Textarea
                id="embed-context"
                value={context}
                onChange={(event) => setContext(event.target.value)}
                placeholder="You are on the pricing page. Answer in German."
                rows={2}
              />
              <p className="text-muted-foreground text-xs">
                Added to the first message of each conversation. It never replaces the agent&apos;s
                own instructions.
              </p>
            </div>

            <div className="flex items-center gap-2">
              <Button
                onClick={submit}
                disabled={create.isPending || !name.trim() || parseOrigins(origins).length === 0}
              >
                Publish widget
              </Button>
              <Button variant="ghost" onClick={reset}>
                Cancel
              </Button>
              {parseOrigins(origins).length === 0 && (
                <span className="text-muted-foreground text-xs">
                  Add at least one site - a widget allowed nowhere cannot open.
                </span>
              )}
            </div>
          </div>
        )}

        {canManage && !creating && (
          <Button variant="outline" onClick={() => setCreating(true)}>
            <Plus className="h-4 w-4" />
            Publish as widget
          </Button>
        )}
      </CardContent>

      {pendingDelete !== null && (
        <ConfirmDialog
          open
          onOpenChange={() => setPendingDelete(null)}
          title={`Remove ${pendingDelete.name}?`}
          description="Every page carrying its key stops working immediately. The key cannot be reissued - a new widget gets a new one."
          confirmLabel="Remove"
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
  const { copy, copied } = useCopyToClipboard();

  return (
    <div className="border-border rounded-lg border p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium">{embed.name}</span>
        <Badge variant={embed.auth_mode === "jwt" ? "secondary" : "outline"}>
          {embed.auth_mode === "jwt" ? "signed-in users" : "public"}
        </Badge>
        {!embed.is_active && <Badge variant="outline">paused</Badge>}
        <div className="flex-1" />
        {canManage && (
          <>
            <Switch
              checked={embed.is_active}
              onCheckedChange={onToggle}
              aria-label={`${embed.is_active ? "Pause" : "Resume"} ${embed.name}`}
            />
            <Button
              variant="ghost"
              size="icon"
              className="text-destructive hover:text-destructive h-8 w-8"
              onClick={onDelete}
              aria-label={`Remove ${embed.name}`}
            >
              <Trash2 className="h-4 w-4" />
            </Button>
          </>
        )}
      </div>

      <div className="mt-3 flex items-start gap-2">
        <code className="bg-muted min-w-0 flex-1 overflow-x-auto rounded-md p-2 font-mono text-xs whitespace-pre">
          {embed.snippet}
        </code>
        <Button
          variant="outline"
          size="sm"
          onClick={() => copy(embed.snippet)}
          aria-label="Copy the snippet"
        >
          {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
        </Button>
      </div>

      <p className="text-muted-foreground mt-2 flex items-center gap-1.5 text-xs">
        <Code2 className="h-3 w-3 shrink-0" />
        <span className={cn("truncate", embed.allowed_origins.length === 0 && "text-destructive")}>
          {embed.allowed_origins.length === 0
            ? "No sites allowed - this widget cannot open anywhere"
            : embed.allowed_origins.join(", ")}
        </span>
      </p>
    </div>
  );
}
