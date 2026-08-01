"use client";

import { Check, ChevronRight, KeyRound, Trash2 } from "lucide-react";

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
   * Whether this panel can create a model, which also decides its shape.
   *
   * Off in the chat on purpose, and the reason is the same one that makes the
   * two layouts different. The chat popover answers one question - which model
   * should *this conversation* run on - so it is a list of what exists. Adding a
   * model is a different act: it creates something every agent in the
   * organization can be pointed at, which is a Builder decision, and in the
   * Builder the form is the panel rather than a state of it.
   */
  allowAdd?: boolean;
  disabled?: boolean;
}

/**
 * Which model to run on: provider, model and key, with the saved ones behind a
 * disclosure.
 *
 * The list used to be the panel and the form was a state you had to reach. That
 * put the wrong thing first. Choosing a model *is* choosing those three fields,
 * and the named profile is the consequence - so a list of consequences somebody
 * else created is not where the decision starts, especially on a fresh
 * deployment where the list is empty and the real control was one click away
 * behind "Add a model".
 *
 * The saved profiles stay, one disclosure down, because a named profile earns
 * its place for a reason the form cannot serve: it is what lets an organization
 * rotate a key or repoint every agent at once. What is gone is its claim on
 * being the first thing anybody sees.
 *
 * Either way the rows keep the vault's vocabulary - provider mark, label,
 * `provider · model`, and the `no key` badge. That badge decides whether the
 * agent can run at all, and it was once visible on the vault page and invisible
 * here.
 */
export function ModelProfilePicker({
  profiles,
  value,
  onChange,
  allowAdd = false,
  disabled,
}: ModelProfilePickerProps) {
  const { deleteProfile } = useModelProviders();
  const selected = profiles.find((profile) => profile.id === value);

  const list = (
    <div role="radiogroup" aria-label="Model" className="space-y-1">
      {profiles.map((profile) => (
        <ProfileRow
          key={profile.id}
          selected={value === profile.id}
          onSelect={() => onChange(profile.id)}
          title={profile.label}
          subtitle={`${profile.provider} · ${profile.model}`}
          provider={profile.provider}
          // A picker that omits this lets somebody publish an agent onto a model
          // that cannot answer. Read from `secret_id` alone: this used to also
          // test a `credential_id` the API has not sent since the vault became
          // the only key store, and `undefined === null` is false - so the badge
          // rendered for no profile at all, including the ones that really had
          // no key.
          noKey={!profile.secret_id}
          disabled={disabled}
          onRemove={allowAdd ? () => deleteProfile.mutate(profile.id) : undefined}
        />
      ))}
    </div>
  );

  // The chat popover chooses between what exists and adds nothing, so it is the
  // list and only the list.
  if (!allowAdd) {
    if (profiles.length === 0) {
      return (
        <div className="border-border rounded-lg border border-dashed p-6 text-center">
          <KeyRound className="text-muted-foreground mx-auto h-5 w-5" />
          <p className="text-muted-foreground mt-2 text-sm">
            This organization has no models yet. An agent cannot run without one.
          </p>
        </div>
      );
    }
    return list;
  }

  return (
    <div className="space-y-3">
      {/* What the agent runs on today, stated before the form that changes it.
          The form is the default view now, and without this line the one fact
          somebody opens this panel to check - which model is this agent on -
          would be the one thing behind a disclosure. */}
      {selected && (
        <div
          // Named, because the same label also appears in the saved-model list
          // below: without it there are two identical strings on this panel and
          // nothing distinguishes "what this agent runs on" from "one of the
          // options".
          role="group"
          aria-label="Current model"
          className="border-border bg-muted/20 flex flex-wrap items-center gap-2 rounded-lg border px-3 py-2"
        >
          <ProviderIcon provider={selected.provider} />
          <span className="min-w-0 flex-1 truncate text-sm">
            <span className="font-medium">{selected.label}</span>
            <span className="text-muted-foreground font-mono text-xs">
              {" "}
              {selected.provider} · {selected.model}
            </span>
          </span>
          {!selected.secret_id && <Badge variant="destructive">no key</Badge>}
        </div>
      )}

      {/* Provider, model and key, always. Choosing a model is picking those three
          things; the named profile is a consequence of the choice rather than the
          way it is made, and a list of previous consequences is not where anybody
          starts. It stays reachable below, because rotating a key or repointing
          every agent at once is exactly what a named profile is for. */}
      <AddModel
        disabled={disabled}
        onCreated={(profile) => {
          // Selected, not merely added: somebody who came here to choose a
          // model has chosen one, and leaving the agent on the old value would
          // make the work look like it did not take.
          onChange(profile.id);
        }}
      />

      {profiles.length > 0 && (
        <details className="group">
          <summary className="text-muted-foreground hover:text-foreground flex cursor-pointer items-center gap-1.5 text-xs">
            <ChevronRight className="h-3 w-3 transition-transform group-open:rotate-90" />
            Use a saved model ({profiles.length})
          </summary>
          <div className="mt-2 space-y-2">
            {list}
            <p className="text-muted-foreground text-xs">
              Named, so an organization can rotate a key or repoint every agent at once.
            </p>
          </div>
        </details>
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
  disabled,
  onRemove,
}: {
  selected: boolean;
  onSelect: () => void;
  title: string;
  subtitle: string;
  provider: string;
  noKey?: boolean;
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
        <ProviderIcon provider={provider} />
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-center gap-1.5">
            <span className="truncate text-sm font-medium">{title}</span>
            {noKey && <Badge variant="destructive">no key</Badge>}
          </span>
          <span className="text-muted-foreground mt-0.5 block truncate font-mono text-xs">
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
