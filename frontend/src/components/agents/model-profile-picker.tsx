"use client";

import { useState } from "react";
import { Check, KeyRound, Plus, Trash2 } from "lucide-react";

import { AddModel } from "@/components/agents/add-model";
import { ProviderIcon } from "@/components/vault/provider-icon";
import { Badge, Button } from "@/components/ui";
import { useModelProviders } from "@/hooks";
import { cn } from "@/lib/utils";
import type { ModelProfile } from "@/types/providers";

interface ModelProfilePickerProps {
  profiles: ModelProfile[];
  /** `null` means "whatever the organization's default is". */
  value: string | null;
  onChange: (profileId: string | null) => void;

  /**
   * Offer to add a model from here.
   *
   * Off by default, and off in the chat on purpose. The chat popover answers
   * one question - which model should *this conversation* run on - and adding a
   * model is a different act: it creates something every agent in the
   * organization can then be pointed at, from a panel somebody opened to change
   * one reply. The Builder is where an agent is configured, so that is where
   * this belongs.
   */
  allowAdd?: boolean;
  disabled?: boolean;
}

/**
 * Which of the organization's models to run on.
 *
 * The same vocabulary the vault uses for the same rows - provider mark, label,
 * `provider · model`, and the badges that say `default` and `no key`. It was a
 * bare list of labels, which meant the one fact that decides whether the agent
 * can run at all, that a profile has no credential behind it, was visible on
 * one page and invisible on the other. A profile is a *named* model precisely
 * so an organization can rotate a key or repoint every agent at once; a picker
 * that shows only the name hides what it is a name for.
 */
export function ModelProfilePicker({
  profiles,
  value,
  onChange,
  allowAdd = false,
  disabled,
}: ModelProfilePickerProps) {
  const [adding, setAdding] = useState(false);
  const { deleteProfile } = useModelProviders();

  if (adding && allowAdd) {
    return (
      <AddModel
        onCancel={() => setAdding(false)}
        onCreated={(profile) => {
          setAdding(false);
          // Selected, not merely added: somebody who came here to choose a
          // model has chosen one, and leaving the agent on the old value would
          // make the work look like it did not take.
          onChange(profile.id);
        }}
      />
    );
  }

  if (profiles.length === 0) {
    return (
      <div className="border-border rounded-lg border border-dashed p-6 text-center">
        <KeyRound className="text-muted-foreground mx-auto h-5 w-5" />
        <p className="text-muted-foreground mt-2 text-sm">
          This organization has no models yet. An agent cannot run without one.
        </p>
        {allowAdd && (
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="mt-3"
            disabled={disabled}
            onClick={() => setAdding(true)}
          >
            <Plus className="h-3.5 w-3.5" />
            Add a model
          </Button>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <div role="radiogroup" aria-label="Model" className="space-y-1">
        {profiles.map((profile) => (
          <ProfileRow
            key={profile.id}
            selected={value === profile.id}
            onSelect={() => onChange(profile.id)}
            title={profile.label}
            subtitle={`${profile.provider} · ${profile.model}`}
            provider={profile.provider}
            // The vault says this on the same row; a picker that omits it lets
            // somebody publish an agent onto a model that cannot answer.
            // Keyed from either store: a model added from the vault carries a
            // `secret_id` and no credential, and reading only the old column
            // marked every one of them "no key".
            noKey={profile.credential_id === null && !profile.secret_id}
            disabled={disabled}
            onRemove={allowAdd ? () => deleteProfile.mutate(profile.id) : undefined}
          />
        ))}
      </div>

      {allowAdd && (
        <div className="flex flex-wrap items-center gap-2 pt-1">
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={disabled}
            onClick={() => setAdding(true)}
          >
            <Plus className="h-3.5 w-3.5" />
            Add a model
          </Button>
          <p className="text-muted-foreground text-xs">
            Named, so an organization can rotate a key or repoint every agent at once.
          </p>
        </div>
      )}
    </div>
  );
}

function ProfileRow({
  selected,
  onSelect,
  title,
  subtitle,
  provider,
  noKey,
  warn,
  disabled,
  onRemove,
}: {
  selected: boolean;
  onSelect: () => void;
  title: string;
  subtitle: string;
  provider?: string;
  noKey?: boolean;
  warn?: boolean;
  disabled?: boolean;
  /** Offered only where models are managed. */
  onRemove?: () => void;
}) {
  return (
    // The radio and the delete are siblings, not nested: a button inside a
    // button is invalid, and the browser resolves it by dropping one of them.
    <div className="flex items-center gap-1">
      <button
        type="button"
        role="radio"
        aria-checked={selected}
        aria-label={title}
        disabled={disabled}
        onClick={onSelect}
        className={cn(
          "flex min-w-0 flex-1 items-center gap-3 rounded-xl border px-3 py-2.5 text-left transition-colors",
          selected ? "border-brand bg-brand/5" : "border-border hover:border-foreground/20",
          disabled && "cursor-not-allowed opacity-60",
        )}
      >
        {provider ? (
          <ProviderIcon provider={provider} />
        ) : (
          <span className="bg-muted h-6 w-6 shrink-0 rounded" aria-hidden />
        )}
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-center gap-1.5">
            <span className="truncate text-sm font-medium">{title}</span>
            {noKey && <Badge variant="destructive">no key</Badge>}
          </span>
          <span
            className={cn(
              "mt-0.5 block truncate font-mono text-xs",
              warn ? "text-destructive" : "text-muted-foreground",
            )}
          >
            {subtitle}
          </span>
        </span>
        {selected && <Check className="text-foreground h-4 w-4 shrink-0" />}
      </button>
      {onRemove && (
        <Button
          type="button"
          variant="ghost"
          size="icon"
          disabled={disabled}
          aria-label={`Remove ${title}`}
          onClick={onRemove}
        >
          <Trash2 className="h-4 w-4" />
        </Button>
      )}
    </div>
  );
}
