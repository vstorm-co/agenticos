"use client";

import { AlertTriangle } from "lucide-react";

import { CapabilityDetail } from "@/components/agents/capability-settings";
import { DelegateList } from "@/components/agents/delegate-list";
import { SchemaForm } from "@/components/agents/schema-form";
import { SpecialistList } from "@/components/agents/specialist-list";
import { Label, Switch } from "@/components/ui";
import { useAgents, usePermissions } from "@/hooks";
import {
  delegationNameClashes,
  readSubagentsConfig,
  SUBAGENTS_ID,
  unboundBinding,
} from "@/lib/agent-spec";
import type {
  CapabilityBindingSpec,
  CapabilityCatalogEntry,
  JsonSchema,
  SubagentRef,
} from "@/types/agents";
import { Perm } from "@/types/permissions";
import { useTranslations } from "next-intl";

/**
 * The two config fields this panel draws itself.
 *
 * Everything else in `SubagentsConfig` is a scalar with a range or a closed set
 * of values, which is exactly what the generated form is for - so a field added
 * to the capability appears here without anybody touching this file. These two
 * cannot be generated: one is a list of nested specs, the other a choice from a
 * set only this agent's own bindings know.
 */
const HAND_ROLLED = ["inline", "share_with_delegates"];

interface SubagentsSectionProps {
  definition: CapabilityCatalogEntry | undefined;
  binding: CapabilityBindingSpec | undefined;
  /** Everything an agent may be given, so a specialist can be given it too. */
  catalog: CapabilityCatalogEntry[];
  /** The parent's own bindings - what `share_with_delegates` may choose from. */
  parentCapabilities: CapabilityBindingSpec[];
  /** The parent's model profile, the fallback when a promoted specialist has none. */
  parentModelProfileId: string | null;
  /** `spec.subagents` - top level, never in the config blob. */
  subagents: SubagentRef[];
  onChange: (binding: CapabilityBindingSpec) => void;
  /** Forwarded to the panel, where the switch now lives - see `CapabilityDetail`. */
  onToggleEnabled?: () => void;
  /** Whether the caller may edit the spec at all - see `CapabilityDetail`. */
  readOnly?: boolean;
  onSubagentsChange: (subagents: SubagentRef[]) => void;
  disabled?: boolean;
}

/**
 * Delegation, as the three separate decisions it actually is.
 *
 * A generated form cannot express any of them. **Delegates** are references to
 * other rows, pinned to a version, and a pin that has fallen behind is the one
 * thing about delegation that nothing else in the product would ever mention.
 * **Specialists** are not versioned at all, which is the fact a reader is most
 * likely to get backwards, so it is said rather than implied by where they sit.
 * **Policy** is the part a schema does render, and it is left to the schema.
 *
 * The three are on one panel because they are one question - "who does this agent
 * hand work to" - and because the rules that bind them are cross-cutting: a name
 * may not be claimed by a delegate and a specialist at once, and `max_fanout`
 * counts both.
 */
export function SubagentsSection({
  definition,
  binding,
  catalog,
  parentCapabilities,
  parentModelProfileId,
  subagents,
  onChange,
  onSubagentsChange,
  onToggleEnabled,
  readOnly,
  disabled,
}: SubagentsSectionProps) {
  const t = useTranslations("agents");
  const { agents } = useAgents();
  const { can } = usePermissions();

  // A deployment that did not register the capability has nothing to configure,
  // and an empty section reads as something that failed to load.
  if (!definition) return null;

  const config = readSubagentsConfig(binding);
  const enabled = binding?.enabled === true;
  // A delegate's own handle is what the parent's model addresses it by, so a
  // slug and a specialist's name are drawn from one namespace.
  const delegateNames = subagents.flatMap((ref) => {
    const agent = agents.find((entry) => entry.id === ref.agent_id);
    return agent === undefined ? [] : [agent.slug];
  });
  const clashes = delegationNameClashes(delegateNames, config.inline);

  const setConfig = (patch: Record<string, unknown>) => {
    if (!binding) return;
    onChange({ ...binding, config: { ...binding.config, ...patch } });
  };

  // Inside the panel's Settings tab rather than above the card, for the reason the
  // workspace's are: these *are* delegation's configuration, and above the card
  // they sat outside the one that names it.
  const controls = (
    <div className="space-y-5">
      {/* The one state a switch cannot say on its own: the spec still carries
          delegates, publish still validates them, and none of them will ever be
          reached. Silence here is how "why is it not delegating" becomes
          unanswerable. */}
      {!enabled && (subagents.length > 0 || config.inline.length > 0) && (
        <div className="flex items-start gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2.5">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
          <p className="text-xs">{t("delegationOffButConfigured")}</p>
        </div>
      )}

      <DelegateList
        agents={agents}
        subagents={subagents}
        onChange={onSubagentsChange}
        clashes={clashes}
        canDelegate={can(Perm.agentsRun)}
        disabled={disabled}
      />

      <SpecialistList
        specialists={config.inline}
        onChange={(inline) => setConfig({ inline })}
        catalog={catalog}
        clashes={clashes}
        parentModelProfileId={parentModelProfileId}
        disabled={disabled}
      />

      <section className="space-y-3">
        <div>
          <p className="text-sm font-medium">{t("delegationPolicyHeading")}</p>
          <p className="text-muted-foreground text-xs">{t("delegationPolicyDetail")}</p>
        </div>

        {definition.config_schema === null ? (
          <p className="text-muted-foreground text-xs">{t("delegationPolicyNoSchema")}</p>
        ) : (
          <SchemaForm
            idPrefix={SUBAGENTS_ID}
            schema={generatedFields(definition.config_schema)}
            value={binding?.config ?? {}}
            disabled={disabled}
            onChange={(next) => setConfig(next)}
          />
        )}

        <ShareWithDelegates
          shared={config.share_with_delegates}
          catalog={catalog}
          // Delegation itself is never shareable: a delegate that inherited it
          // would delegate on, and depth is what `max_depth` bounds.
          bound={
            new Set(
              parentCapabilities
                .filter((entry) => entry.enabled && entry.id !== SUBAGENTS_ID)
                .map((entry) => entry.id),
            )
          }
          disabled={disabled}
          onChange={(share_with_delegates) => setConfig({ share_with_delegates })}
        />
      </section>
    </div>
  );

  // Rendered whether or not the capability is granted: the switch that grants it
  // is on its title row, and the controls are inert until it is.
  return (
    <CapabilityDetail
      binding={binding ?? unboundBinding(definition.id)}
      definition={definition}
      onChange={onChange}
      onToggleEnabled={onToggleEnabled}
      readOnly={readOnly}
      disabled={disabled}
      settingsExtra={controls}
      // The three sections above *are* this capability's configuration; the
      // generated form would draw the policy fields a second time.
      hideConfigForm
    />
  );
}

/**
 * The schema with the fields this panel draws itself taken out.
 *
 * Subtracting rather than listing what to keep: a field added to
 * `SubagentsConfig` should appear here on its own, which is the whole reason the
 * backend publishes a schema at all.
 */
function generatedFields(schema: JsonSchema): JsonSchema {
  const properties = Object.fromEntries(
    Object.entries(schema.properties ?? {}).filter(([name]) => !HAND_ROLLED.includes(name)),
  );
  return { ...schema, properties };
}

interface ShareWithDelegatesProps {
  shared: string[];
  /** The catalog, for the names. */
  catalog: CapabilityCatalogEntry[];
  /** The ids the parent is actually bound to - the only ones offered. */
  bound: ReadonlySet<string>;
  disabled?: boolean;
  onChange: (shared: string[]) => void;
}

/**
 * Which of the parent's capabilities its delegates inherit.
 *
 * A delegate runs on its own spec, so by default it can do only what its own
 * spec grants. This is the exception, and it is deliberately narrow: only what
 * the parent is *itself* bound to may be shared, because sharing a capability
 * nobody granted the parent would make a delegate the quiet route to one the
 * organization refused.
 */
function ShareWithDelegates({
  shared,
  catalog,
  bound,
  disabled,
  onChange,
}: ShareWithDelegatesProps) {
  const t = useTranslations("agents");
  const shareable = catalog.filter((entry) => bound.has(entry.id));
  const chosen = new Set(shared);

  return (
    <div className="space-y-1.5">
      <Label>{t("shareWithDelegates")}</Label>
      <p className="text-muted-foreground text-xs">{t("shareWithDelegatesDetail")}</p>
      {shareable.length === 0 ? (
        <p className="text-muted-foreground text-xs">{t("nothingToShareWithDelegates")}</p>
      ) : (
        <div className="grid gap-1.5 sm:grid-cols-2">
          {shareable.map((entry) => (
            <div
              key={entry.id}
              className="border-border flex items-center justify-between gap-2 rounded-md border px-2.5 py-1.5"
            >
              <span className="truncate text-sm">{entry.name}</span>
              <Switch
                checked={chosen.has(entry.id)}
                disabled={disabled}
                aria-label={t("shareCapabilityWithDelegates", { name: entry.name })}
                onCheckedChange={(on) =>
                  onChange(
                    on ? [...shared, entry.id] : shared.filter((entry_id) => entry_id !== entry.id),
                  )
                }
              />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
