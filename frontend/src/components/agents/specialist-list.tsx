"use client";

import { useState } from "react";
import { Plus, Trash2 } from "lucide-react";

import { CapabilitySettings } from "@/components/agents/capability-settings";
import { CollectionPicker } from "@/components/agents/collection-picker";
import { DelegationModeField } from "@/components/agents/delegation-mode-field";
import { ModelProfilePicker } from "@/components/agents/model-profile-picker";
import { SkillGallery } from "@/components/agents/skill-gallery";
import { Button, Input, Label, Switch, Textarea } from "@/components/ui";
import { useKnowledgeBases, useModelProviders, useSkills } from "@/hooks";
import {
  newSpecialist,
  specialistNameError,
  SUBAGENTS_ID,
  withCapability,
  withSkills,
} from "@/lib/agent-spec";
import { cn } from "@/lib/utils";
import type { CapabilityBindingSpec, CapabilityCatalogEntry, SpecialistSpec } from "@/types/agents";
import { useTranslations } from "next-intl";

interface SpecialistListProps {
  specialists: SpecialistSpec[];
  onChange: (specialists: SpecialistSpec[]) => void;
  /** Everything an agent may be given; a specialist may be given it too. */
  catalog: CapabilityCatalogEntry[];
  clashes: ReadonlySet<string>;
  disabled?: boolean;
}

/**
 * Specialists defined here rather than published, and said to be exactly that.
 *
 * A "summarise this in three bullets" helper should not require somebody to
 * publish an agent, and this is that. The line under the heading is not
 * decoration: a specialist has no version row, cannot be pinned, cannot be
 * referenced by anything else, and changes the moment this agent is edited -
 * which is the whole difference from a delegate, and the one thing a reader
 * would otherwise assume the other way round.
 *
 * Master-detail, for the reason the capability workbench is: five specialists
 * stacked as five open editors is five sets of instructions between the name and
 * the thing it names.
 */
export function SpecialistList({
  specialists,
  onChange,
  catalog,
  clashes,
  disabled,
}: SpecialistListProps) {
  const t = useTranslations("agents");
  const [chosen, setChosen] = useState(0);
  // Clamped rather than stored back: removing the last specialist leaves the
  // index past the end, and an editor for `undefined` is a blank panel that
  // reads as a failure to render.
  const index = chosen < specialists.length ? chosen : 0;
  const specialist = specialists[index];

  const patch = (changes: Partial<SpecialistSpec>) =>
    onChange(specialists.map((entry, at) => (at === index ? { ...entry, ...changes } : entry)));

  return (
    <section className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm font-medium">{t("specialistsHeading")}</p>
          <p className="text-muted-foreground text-xs">{t("specialistsNotVersioned")}</p>
        </div>
        <Button
          variant="outline"
          size="sm"
          disabled={disabled}
          onClick={() => {
            onChange([...specialists, newSpecialist()]);
            setChosen(specialists.length);
          }}
        >
          <Plus className="h-3.5 w-3.5" />
          {t("addSpecialist")}
        </Button>
      </div>

      {specialist === undefined ? (
        <p className="text-muted-foreground border-border rounded-lg border border-dashed px-3 py-4 text-xs">
          {t("noSpecialistsYet")}
        </p>
      ) : (
        <div className="space-y-3">
          <div className="flex flex-wrap gap-1.5">
            {specialists.map((entry, at) => (
              <button
                key={at}
                type="button"
                onClick={() => setChosen(at)}
                aria-current={at === index ? "true" : undefined}
                className={cn(
                  "rounded-md border px-2.5 py-1 text-xs",
                  at === index ? "border-foreground/25 bg-accent" : "hover:bg-accent/50",
                )}
              >
                {entry.name === "" ? t("specialistUnnamed") : entry.name}
              </button>
            ))}
          </div>

          <SpecialistEditor
            specialist={specialist}
            catalog={catalog}
            clashes={clashes}
            disabled={disabled}
            onChange={patch}
            onRemove={() => {
              onChange(specialists.filter((_, at) => at !== index));
              setChosen(0);
            }}
          />
        </div>
      )}
    </section>
  );
}

interface SpecialistEditorProps {
  specialist: SpecialistSpec;
  catalog: CapabilityCatalogEntry[];
  clashes: ReadonlySet<string>;
  disabled?: boolean;
  onChange: (changes: Partial<SpecialistSpec>) => void;
  onRemove: () => void;
}

/**
 * What a specialist is: its name, what the parent's model reads about it, and
 * its instructions.
 *
 * Split from what it may *use* below because the two are read at different
 * moments - the name and description are the interface the parent's model sees,
 * and the resources are what the specialist itself gets.
 */
function SpecialistEditor({
  specialist,
  catalog,
  clashes,
  disabled,
  onChange,
  onRemove,
}: SpecialistEditorProps) {
  const t = useTranslations("agents");
  const nameKey = specialistNameError(specialist.name);
  const clash = clashes.has(specialist.name);

  return (
    <div className="border-border space-y-4 rounded-lg border p-4">
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1.5">
          <Label htmlFor="specialist-name">{t("specialistName")}</Label>
          <Input
            id="specialist-name"
            value={specialist.name}
            disabled={disabled}
            spellCheck={false}
            aria-invalid={nameKey !== null || clash}
            className="font-mono text-sm"
            onChange={(event) => onChange({ name: event.target.value })}
          />
          {nameKey !== null && <p className="text-destructive text-xs">{t(nameKey)}</p>}
          {nameKey === null && clash && (
            <p className="text-destructive text-xs">
              {t("specialistNameClash", { name: specialist.name })}
            </p>
          )}
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="specialist-max-steps">{t("specialistMaxSteps")}</Label>
          <Input
            id="specialist-max-steps"
            type="number"
            min="1"
            max="200"
            value={specialist.max_steps ?? ""}
            disabled={disabled}
            placeholder={t("specialistSameAsParent")}
            onChange={(event) =>
              onChange({ max_steps: event.target.value ? Number(event.target.value) : null })
            }
          />
        </div>
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="specialist-description">{t("specialistDescription")}</Label>
        <Textarea
          id="specialist-description"
          value={specialist.description}
          rows={2}
          disabled={disabled}
          onChange={(event) => onChange({ description: event.target.value })}
        />
        <p className="text-muted-foreground text-xs">{t("specialistDescriptionDetail")}</p>
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="specialist-instructions">{t("specialistInstructions")}</Label>
        <Textarea
          id="specialist-instructions"
          value={specialist.instructions}
          rows={6}
          disabled={disabled}
          onChange={(event) => onChange({ instructions: event.target.value })}
        />
      </div>

      <SpecialistResources
        specialist={specialist}
        catalog={catalog}
        disabled={disabled}
        onChange={onChange}
      />

      <div className="flex justify-end">
        <Button variant="ghost" size="sm" disabled={disabled} onClick={onRemove}>
          <Trash2 className="h-3.5 w-3.5" />
          {t("removeSpecialist")}
        </Button>
      </div>
    </div>
  );
}

/**
 * What a specialist may use: a model, capabilities, collections and skills.
 *
 * It reads the three catalogs itself rather than taking them as props. All three
 * are already fetched by the Builder around it, so this costs no request - and
 * threading them down through the capability workbench, which has no use for any
 * of them, would make the workbench know what a specialist is.
 */
function SpecialistResources({
  specialist,
  catalog,
  disabled,
  onChange,
}: {
  specialist: SpecialistSpec;
  catalog: CapabilityCatalogEntry[];
  disabled?: boolean;
  onChange: (changes: Partial<SpecialistSpec>) => void;
}) {
  const t = useTranslations("agents");
  const { profiles } = useModelProviders();
  const { kbs: collections } = useKnowledgeBases();
  const { skills, total: skillCount } = useSkills({ limit: 100 });

  const toggleId = (list: string[], value: string) =>
    list.includes(value) ? list.filter((entry) => entry !== value) : [...list, value];

  return (
    <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-1.5">
          <Label>{t("specialistModel")}</Label>
          <ModelProfilePicker
            profiles={profiles}
            value={specialist.model_profile_id ?? null}
            disabled={disabled}
            onChange={(model_profile_id) => onChange({ model_profile_id })}
          />
        </div>
        <DelegationModeField
          id="specialist-mode"
          value={specialist.preferred_mode ?? null}
          disabled={disabled}
          onChange={(preferred_mode) => onChange({ preferred_mode })}
        />
      </div>

      <SpecialistCapabilities
        catalog={catalog}
        bindings={specialist.capabilities}
        disabled={disabled}
        onChange={(capabilities) => onChange({ capabilities })}
      />

      <div className="space-y-1.5">
        <Label>{t("specialistCollections")}</Label>
        <CollectionPicker
          collections={collections}
          selectedIds={specialist.collection_ids}
          disabled={disabled}
          onToggle={(id) => onChange({ collection_ids: toggleId(specialist.collection_ids, id) })}
        />
      </div>

      <div className="space-y-1.5">
        <Label>{t("specialistSkills")}</Label>
        <SkillGallery
          skills={skills}
          total={skillCount}
          selectedIds={specialist.skill_ids}
          disabled={disabled}
          // The same coupling the parent has: `skill_ids` resolves the skills,
          // and the `skills` capability is what turns them into tools. Bound
          // without it they are fetched and thrown away.
          onToggle={(id) => onChange(withSkills(specialist, toggleId(specialist.skill_ids, id)))}
        />
      </div>
    </div>
  );
}

/**
 * What a specialist can do, granted from the same catalog and configured by the
 * same panel as the parent's own.
 *
 * `CapabilitySettings` one level down, deliberately: a specialist carries real
 * `CapabilityBindingSpec` bindings, validated at publish exactly as an agent's
 * are, so a second editor here would be a second set of defaults for approval,
 * secrets and tool overrides - and the copy is the bug this whole shape exists
 * to avoid.
 *
 * Delegation itself is not offered. A specialist does not delegate further:
 * nesting is what `max_depth` bounds, and it is bounded for published delegates,
 * which are reviewable.
 */
function SpecialistCapabilities({
  catalog,
  bindings,
  onChange,
  disabled,
}: {
  catalog: CapabilityCatalogEntry[];
  bindings: CapabilityBindingSpec[];
  onChange: (bindings: CapabilityBindingSpec[]) => void;
  disabled?: boolean;
}) {
  const t = useTranslations("agents");
  const grantable = catalog.filter((entry) => entry.id !== SUBAGENTS_ID);
  const on = new Set(bindings.filter((binding) => binding.enabled).map((binding) => binding.id));

  return (
    <div className="space-y-2">
      <p className="text-muted-foreground text-xs font-medium tracking-wide uppercase">
        {t("specialistCapabilities")}
      </p>
      <div className="grid gap-1.5 sm:grid-cols-2">
        {grantable.map((entry) => (
          <div
            key={entry.id}
            className="border-border flex items-center justify-between gap-2 rounded-md border px-2.5 py-1.5"
          >
            <span className="truncate text-sm">{entry.name}</span>
            <Switch
              checked={on.has(entry.id)}
              disabled={disabled}
              aria-label={t("giveSpecialistCapability", { name: entry.name })}
              onCheckedChange={() =>
                onChange(withCapability(bindings, entry.id, !on.has(entry.id)))
              }
            />
          </div>
        ))}
      </div>
      <CapabilitySettings
        catalog={grantable}
        selected={bindings}
        disabled={disabled}
        onChange={(binding) =>
          onChange(bindings.map((entry) => (entry.id === binding.id ? binding : entry)))
        }
      />
    </div>
  );
}
