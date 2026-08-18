"use client";

import { useId } from "react";
import { Check, ChevronRight, KeyRound, Trash2 } from "lucide-react";

import { AddModel } from "@/components/agents/add-model";
import { ProviderIcon } from "@/components/vault/provider-icon";
import { Badge, Button } from "@/components/ui";
import { useModelProviders } from "@/hooks";
import { modelDetail } from "@/lib/model-profiles";
import { cn } from "@/lib/utils";
import type { ModelProfile } from "@/types/providers";
import { useTranslations } from "next-intl";

interface ModelProfilePickerProps {
  profiles: ModelProfile[];
  /** `null` means "whatever the organization's default is". */
  value: string | null;
  onChange: (profileId: string | null) => void;

  /**
   * Whether this panel can create a model, which also decides its shape.
   *
   * Off where the panel only chooses between models somebody else defined - the
   * specialist row answers one question, which model should *this* delegate run
   * on, so it is a list of what exists. Adding a model is a different act: it
   * creates something every agent in the organization can be pointed at, and
   * where that is allowed the form is the panel rather than a state of it.
   */
  allowAdd?: boolean;
  /**
   * Whether a saved model can be deleted from here.
   *
   * Its own flag rather than a second meaning of `allowAdd`, because the two are
   * different claims. Creating a model adds something agents may be pointed at;
   * deleting one takes away something they already are, from under every agent
   * in the organization at once. The Builder is where an organization's models
   * are managed, so it offers both. The knowledge-base dialog needs to name a
   * model and store a key for it and nothing more, so it gets the first and not
   * the second - which is the whole reason this split exists.
   */
  allowRemove?: boolean;
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
 *
 * Two flags, not one. `allowAdd` decides the shape - the form and its inline
 * key field, or a list of what exists; `allowRemove` decides whether a saved
 * model can be deleted from here. They were the same flag until the
 * knowledge-base dialog needed one without the other.
 *
 * The current-model line renders in both shapes. It says whether the profile
 * that will actually be used has a key, which is the fact that decides whether
 * the run - or the ingestion - can happen at all, and it is not something one
 * caller should get and another should have to infer from a list.
 */
export function ModelProfilePicker({
  profiles,
  value,
  onChange,
  allowAdd = false,
  allowRemove = false,
  disabled,
}: ModelProfilePickerProps) {
  const t = useTranslations("agents");
  const { deleteProfile } = useModelProviders();
  const selected = profiles.find((profile) => profile.id === value);
  // Generated rather than a constant: the Builder and a dialog can both have a
  // picker mounted, and two elements answering to one id makes the second group's
  // accessible name the first one's caption.
  const captionId = useId();

  const list = (
    <div role="radiogroup" aria-label={t("model2")} className="space-y-1">
      {profiles.map((profile) => (
        <ProfileRow
          key={profile.id}
          selected={value === profile.id}
          onSelect={() => onChange(profile.id)}
          title={profile.label}
          subtitle={modelDetail(profile)}
          provider={profile.provider}
          // A picker that omits this lets somebody publish an agent onto a model
          // that cannot answer. Read from `secret_id` alone: this used to also
          // test a `credential_id` the API has not sent since the vault became
          // the only key store, and `undefined === null` is false - so the badge
          // rendered for no profile at all, including the ones that really had
          // no key.
          noKey={!profile.secret_id}
          disabled={disabled}
          onRemove={allowRemove ? () => deleteProfile.mutate(profile.id) : undefined}
        />
      ))}
    </div>
  );

  // Which of the organization's models this agent runs on, by name.
  //
  // **The name and nothing else**, which is the whole history of this line: it used
  // to print `provider · model` after a label that already *was* `provider · model`,
  // so it read the pair twice. Then it was deleted, and four things turned out to be
  // reading it - three journeys and the knowledge-base dialog's "this model cannot
  // run" - because it is the only place that answers *which named profile* is in
  // use. The two fields below answer the technical pair; this answers the name, and
  // between them nothing is said twice.
  const current = selected ? (
    <div
      role="group"
      aria-labelledby={captionId}
      className="border-border bg-muted/20 flex flex-wrap items-center gap-2 rounded-lg border px-3 py-2"
    >
      <span id={captionId} className="text-muted-foreground text-xs">
        {t("currentModel")}
      </span>
      <ProviderIcon provider={selected.provider} />
      <span className="min-w-0 flex-1 truncate text-sm font-medium">{selected.label}</span>
      {/* The badge that decides whether the agent can run at all. In a list of a
          dozen saved models the chosen one's badge is a badge among twelve. */}
      {!selected.secret_id && <Badge variant="destructive">{t("noKey")}</Badge>}
    </div>
  ) : null;

  // A panel that only chooses between what exists is the list, and the line
  // saying which of them is in use.
  if (!allowAdd) {
    if (profiles.length === 0) {
      // No models, and this caller cannot add one — the Builder hid the form
      // above. Say why and where the fix is, rather than leave them to discover it
      // at publish: an agent with no model is refused there, and the only ways to
      // one are a permission they lack or an admin who holds it.
      return (
        <div className="border-border rounded-lg border border-dashed p-6 text-center">
          <KeyRound className="text-muted-foreground mx-auto h-5 w-5" />
          <p className="text-muted-foreground mt-2 text-sm">{t("organizationHasNoModels")}</p>
          <p className="text-muted-foreground mx-auto mt-1 max-w-sm text-xs">
            {t("noModelAskAdmin")}
          </p>
        </div>
      );
    }
    return (
      <div className="space-y-3">
        {current}
        {list}
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {current}

      {/* Provider, model and key, always - and starting on the model in use, so the
          panel says what that is in the same two fields that change it rather than
          in a line above them. Choosing a model *is* picking those three things; the
          named profile is a consequence of the choice rather than the way it is
          made. It stays reachable below, because rotating a key or repointing every
          agent at once is exactly what a named profile is for.

          Keyed on the selection so the fields follow it: picking a saved model from
          the disclosure below has to move them, and derived state that only reads
          its prop once would leave them on whatever was selected at mount.

          On the *profile*, not on `value`, because the two are not available at the
          same moment: an agent already pointed at one renders with `value` set while
          the profiles are still in flight, so a key of `value` never changes once
          they land and the form keeps the empty fields it mounted with. Which is
          "Choose a provider" above an agent that plainly has one, for as long as the
          list took - green on a warm laptop and red in CI. */}
      <AddModel
        key={selected?.id ?? "none"}
        selected={selected}
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
            {t("useSavedModelCount", { count: profiles.length })}
          </summary>
          <div className="mt-2 space-y-2">
            {list}
            <p className="text-muted-foreground text-xs">{t("namedSoOrganizationCan")}</p>
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
  /** `null` where the title already names the provider and the model. */
  subtitle: string | null;
  provider: string;
  noKey?: boolean;
  disabled?: boolean;
  /** Offered only where models are managed. */
  onRemove?: () => void;
}) {
  const t = useTranslations("agents");
  const tc = useTranslations("common");
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
            {noKey && <Badge variant="destructive">{t("noKey2")}</Badge>}
          </span>
          {subtitle !== null && (
            <span className="text-muted-foreground mt-0.5 block truncate font-mono text-xs">
              {subtitle}
            </span>
          )}
        </span>
        {selected && <Check className="text-foreground h-4 w-4 shrink-0" />}
      </button>
      {onRemove && (
        <Button
          type="button"
          variant="ghost"
          size="icon"
          disabled={disabled}
          aria-label={tc("removeNamed", { name: title })}
          onClick={onRemove}
        >
          <Trash2 className="h-4 w-4" />
        </Button>
      )}
    </div>
  );
}
