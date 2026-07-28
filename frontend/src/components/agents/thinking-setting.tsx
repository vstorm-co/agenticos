"use client";

import { SchemaForm } from "@/components/agents/schema-form";
import { Label, Switch } from "@/components/ui";
import type { CapabilityBindingSpec, CapabilityCatalogEntry } from "@/types/agents";

interface ThinkingSettingProps {
  definition: CapabilityCatalogEntry | undefined;
  binding: CapabilityBindingSpec | undefined;
  onToggle: () => void;
  onChange: (binding: CapabilityBindingSpec) => void;
  disabled?: boolean;
}

/**
 * Reasoning effort, shown with the model settings rather than with capabilities.
 *
 * It is a capability in the spec and stays one — it is Pydantic AI's own
 * `Thinking`, and moving it out of `capabilities` would be a spec migration for
 * a change of heading. But it contributes no tools: it changes how the model
 * runs, not what the agent can do, which is the question the capability list
 * answers. Sitting among things that grant an agent abilities, it read as one.
 */
export function ThinkingSetting({
  definition,
  binding,
  onToggle,
  onChange,
  disabled,
}: ThinkingSettingProps) {
  // The capability is registered by the backend; a deployment without it has
  // nothing to offer here and says nothing rather than an empty control.
  if (!definition) return null;

  const on = binding?.enabled ?? false;

  return (
    <div className="border-border space-y-3 rounded-lg border p-4">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <Label htmlFor="agent-thinking">{definition.name}</Label>
          <p className="text-muted-foreground mt-1 text-xs">{definition.description}</p>
        </div>
        <Switch
          id="agent-thinking"
          checked={on}
          disabled={disabled}
          onCheckedChange={onToggle}
          aria-label={definition.name}
        />
      </div>

      {on && binding && definition.config_schema && (
        <SchemaForm
          idPrefix={binding.id}
          schema={definition.config_schema}
          value={binding.config}
          disabled={disabled}
          onChange={(config) => onChange({ ...binding, config })}
        />
      )}
    </div>
  );
}
