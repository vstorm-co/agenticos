"use client";

import { useState } from "react";
import { ExternalLink, Eye, EyeOff, KeyRound, Plus } from "lucide-react";

import { Button, Input, Label } from "@/components/ui";
import { useSecrets } from "@/hooks";
import { ROUTES } from "@/lib/constants";
import type { StorableSecretKind } from "@/types/secrets";
import { useTranslations } from "next-intl";

interface InlineSecretProps {
  /** What shape the caller needs. Almost always `api_key`. */
  kind: StorableSecretKind;
  /**
   * What the key is for - a provider or service id.
   *
   * Recorded because it is what makes the key findable afterwards: a model
   * picker offers the providers you hold keys for, and a web-search binding
   * offers the Tavily ones. A key stored without it is a key only the person
   * who added it can place.
   */
  purpose: string;
  /** Suggested name - "Tavily", "OpenAI" - so nobody has to invent one. */
  suggestedName: string;
  /** Where to get the key, when there is an obvious answer. */
  helpUrl?: string;
  /** Called with the new secret's id once it is stored. */
  onCreated: (secretId: string) => void;
  disabled?: boolean;
}

/**
 * Add a key without leaving the page that needs it.
 *
 * The flow this replaces: pick a service, be told it needs a key, open the
 * vault in another tab, add the key, come back, re-pick the service, then find
 * the picker did not refresh. Four steps and a context switch to answer one
 * question the form had already asked.
 *
 * It still writes to the same vault as the Vault page - this is a shortcut to
 * it, not a second store. The value goes straight out and is never read back,
 * which is why the field is cleared the moment it is submitted rather than left
 * sitting in a React state somewhere.
 *
 * Only `api_key` is offered here. The other shapes - an AWS pair, a Google
 * service-account JSON, an Azure deployment - are multi-field forms with their own
 * validation, and the honest place for those is the Vault. Which is why the link to
 * it is not conditional: a picker that offers only the keys already stored, with
 * nowhere to go when the shape needed is not an opaque token, is a dead end. It
 * opens in a new tab so the half-filled form behind it survives.
 */
export function InlineSecret({
  kind,
  purpose,
  suggestedName,
  helpUrl,
  onCreated,
  disabled,
}: InlineSecretProps) {
  const t = useTranslations("vault");
  const { create } = useSecrets();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState(suggestedName);
  const [value, setValue] = useState("");
  const [revealed, setRevealed] = useState(false);

  if (!open) {
    return (
      <div className="flex flex-wrap items-center gap-3">
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={disabled}
          onClick={() => {
            setName(suggestedName);
            setOpen(true);
          }}
        >
          <Plus className="h-3.5 w-3.5" />
          Add a key
        </Button>
        {/* Beside it, always. This form takes one shape - an opaque `api_key` -
            and the vault takes every other: an AWS pair, a service-account JSON,
            an Azure deployment. A picker offering only what is already stored,
            with nowhere to go when the needed shape is not one of them, is a dead
            end; a new tab is what keeps the half-filled form on this page. */}
        <a
          href={ROUTES.VAULT}
          target="_blank"
          rel="noreferrer noopener"
          className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-xs underline underline-offset-4"
        >
          <ExternalLink className="h-3 w-3" aria-hidden />
          Open the Vault
        </a>
      </div>
    );
  }

  const submit = () => {
    create.mutate(
      { name: name.trim(), value: { kind, api_key: value }, purpose },
      {
        onSuccess: (secret) => {
          onCreated(secret.id);
          setRevealed(false);
          // Cleared immediately: the value has left, and nothing on this page
          // has any further use for it.
          setValue("");
          setOpen(false);
        },
      },
    );
  };

  return (
    <div className="border-border space-y-3 rounded-lg border border-dashed p-3">
      <p className="text-muted-foreground flex items-center gap-1.5 text-xs">
        <KeyRound className="h-3.5 w-3.5 shrink-0" />
        Stored in this organization&apos;s vault, encrypted, and never shown again.
      </p>

      <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,1.6fr)]">
        <div className="space-y-1.5">
          <Label htmlFor="inline-secret-name" className="text-xs">
            Name
          </Label>
          <Input
            id="inline-secret-name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder={suggestedName}
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="inline-secret-value" className="text-xs">
            Key
          </Label>
          <div className="relative">
            <Input
              id="inline-secret-value"
              type={revealed ? "text" : "password"}
              value={value}
              onChange={(event) => setValue(event.target.value)}
              placeholder={t("pasteHere")}
              autoComplete="off"
              className="pr-10 font-mono"
            />
            {/* The one moment this value can be checked: it is written once and
                never shown again, and a paste that picked up a newline or half
                a key looks exactly like a correct one behind dots. */}
            <button
              type="button"
              onClick={() => setRevealed((shown) => !shown)}
              aria-label={revealed ? "Hide key" : "Show key"}
              aria-pressed={revealed}
              className="text-muted-foreground hover:text-foreground absolute top-1/2 right-1 -translate-y-1/2 rounded-md p-2"
            >
              {revealed ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </button>
          </div>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Button
          type="button"
          size="sm"
          disabled={create.isPending || !name.trim() || !value.trim()}
          onClick={submit}
        >
          Save key
        </Button>
        <Button type="button" size="sm" variant="ghost" onClick={() => setOpen(false)}>
          Cancel
        </Button>
        <a
          href={ROUTES.VAULT}
          target="_blank"
          rel="noreferrer noopener"
          className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-xs underline underline-offset-4"
        >
          <ExternalLink className="h-3 w-3" aria-hidden />
          Open the Vault
        </a>
        {helpUrl && (
          <a
            href={helpUrl}
            target="_blank"
            rel="noreferrer noopener"
            className="text-muted-foreground ml-auto text-xs underline underline-offset-4"
          >
            Where do I get one?
          </a>
        )}
      </div>
    </div>
  );
}
