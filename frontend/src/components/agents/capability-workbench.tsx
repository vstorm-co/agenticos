"use client";

import { useMemo, useState } from "react";
import { Check, ShieldAlert, Wrench } from "lucide-react";

import { CapabilityDetail } from "@/components/agents/capability-settings";
import { Badge, SearchInput } from "@/components/ui";
import { cn } from "@/lib/utils";
import type { CapabilityBindingSpec, CapabilityCatalogEntry } from "@/types/agents";

interface CapabilityWorkbenchProps {
  catalog: CapabilityCatalogEntry[];
  selected: CapabilityBindingSpec[];
  onToggle: (capabilityId: string) => void;
  onChange: (binding: CapabilityBindingSpec) => void;
  disabled?: boolean;
}

/**
 * Choose what an agent can do, and configure the one you are looking at.
 *
 * Master–detail rather than a grid of checkboxes over a pile of settings cards.
 * The pile was the problem: switching on five capabilities produced five
 * configuration panels stacked below the grid, each one separated from the
 * checkbox that created it by everything else somebody had switched on. The
 * settings were not missing - a tool's name and description have been editable
 * per agent all along - they were simply somewhere nobody looked.
 *
 * Focus and enablement are deliberately different things. You can read what a
 * capability offers, down to the arguments of each tool, before deciding to
 * give it to an agent; and an enabled capability does not steal the panel from
 * the one you were reading.
 */
export function CapabilityWorkbench({
  catalog,
  selected,
  onToggle,
  onChange,
  disabled,
}: CapabilityWorkbenchProps) {
  const enabled = new Set(selected.filter((binding) => binding.enabled).map((b) => b.id));
  const [focusedId, setFocusedId] = useState<string | null>(null);

  // Filtered, not paged: this column is navigation, and a capability that moved
  // to page two of its own picker is one nobody finds. The tools are searched
  // too - somebody looking for "chart" is looking for the tool, and has no
  // reason to know which capability owns it.
  const [query, setQuery] = useState("");
  const categories = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const matching = needle
      ? catalog.filter(
          (entry) =>
            entry.name.toLowerCase().includes(needle) ||
            entry.description.toLowerCase().includes(needle) ||
            entry.tools.some((tool) => tool.name.toLowerCase().includes(needle)),
        )
      : catalog;
    const names = [...new Set(matching.map((entry) => entry.category))].sort();
    return names.map((name) => ({
      name,
      entries: matching.filter((entry) => entry.category === name),
    }));
  }, [catalog, query]);

  // Falls back to the first thing on the list rather than to nothing: an empty
  // right-hand column on first load reads as a panel that failed to render.
  const focused =
    catalog.find((entry) => entry.id === focusedId) ??
    catalog.find((entry) => enabled.has(entry.id)) ??
    catalog[0];
  const binding = selected.find((entry) => entry.id === focused?.id);

  if (catalog.length === 0) return null;

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,18rem)_minmax(0,1fr)]">
      <div className="space-y-3">
        {catalog.length > 8 && (
          <SearchInput
            value={query}
            onChange={setQuery}
            placeholder="Search capabilities…"
            className="w-full sm:w-full"
          />
        )}

        <div className="space-y-4 lg:max-h-[36rem] lg:overflow-y-auto lg:pr-1">
          {categories.length === 0 && (
            <p className="text-muted-foreground px-1 py-6 text-sm">
              No capability or tool matches “{query}”.
            </p>
          )}
          {categories.map((category) => (
            <div key={category.name} className="space-y-1">
              <p className="text-muted-foreground px-1 text-[11px] font-medium tracking-wide uppercase">
                {category.name}
              </p>
              {category.entries.map((entry) => (
                <CapabilityRow
                  key={entry.id}
                  entry={entry}
                  enabled={enabled.has(entry.id)}
                  focused={focused?.id === entry.id}
                  disabled={disabled}
                  onFocus={() => setFocusedId(entry.id)}
                  onToggle={() => onToggle(entry.id)}
                />
              ))}
            </div>
          ))}
        </div>
      </div>

      <div className="min-w-0">
        {focused && binding?.enabled ? (
          <CapabilityDetail
            binding={binding}
            definition={focused}
            onChange={onChange}
            disabled={disabled}
          />
        ) : focused ? (
          <CapabilityPreview
            entry={focused}
            disabled={disabled}
            onEnable={() => onToggle(focused.id)}
          />
        ) : null}
      </div>
    </div>
  );
}

function CapabilityRow({
  entry,
  enabled,
  focused,
  disabled,
  onFocus,
  onToggle,
}: {
  entry: CapabilityCatalogEntry;
  enabled: boolean;
  focused: boolean;
  disabled?: boolean;
  onFocus: () => void;
  onToggle: () => void;
}) {
  return (
    <div
      className={cn(
        "flex items-start gap-2 rounded-lg border px-2 py-2 transition-colors",
        focused ? "border-foreground/25 bg-accent" : "hover:bg-accent/50 border-transparent",
      )}
    >
      {/* The checkbox is its own control, not the row. Reading what a capability
          offers must not be the same gesture as granting it. */}
      <button
        type="button"
        role="checkbox"
        aria-checked={enabled}
        aria-label={`Give this agent ${entry.name}`}
        disabled={disabled}
        onClick={onToggle}
        className={cn(
          "mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded border transition-colors",
          enabled ? "border-brand bg-brand text-brand-foreground" : "border-input",
          disabled && "cursor-not-allowed opacity-60",
        )}
      >
        {enabled && <Check className="h-3 w-3" />}
      </button>

      <button
        type="button"
        onClick={onFocus}
        aria-current={focused ? "true" : undefined}
        className="min-w-0 flex-1 text-left"
      >
        <span className="flex flex-wrap items-center gap-1.5">
          <span className="text-sm font-medium">{entry.name}</span>
          {entry.side_effecting && (
            <ShieldAlert className="text-muted-foreground h-3 w-3" aria-label="acts on the world" />
          )}
        </span>
        <span className="text-muted-foreground mt-0.5 block text-xs">
          {entry.tools.length === 0
            ? "no tools - changes how it runs"
            : entry.tools.length === 1
              ? "1 tool"
              : `${entry.tools.length} tools`}
        </span>
      </button>
    </div>
  );
}

/**
 * A capability nobody has switched on, read rather than configured.
 *
 * Its tools are the whole of what it is, so they are what the panel shows -
 * the alternative is asking someone to grant a capability to find out what
 * granting it does.
 */
function CapabilityPreview({
  entry,
  disabled,
  onEnable,
}: {
  entry: CapabilityCatalogEntry;
  disabled?: boolean;
  onEnable: () => void;
}) {
  return (
    <div className="border-border bg-card rounded-xl border p-5">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium">{entry.name}</span>
        <span className="text-muted-foreground font-mono text-xs">{entry.id}</span>
        {entry.side_effecting && (
          <Badge variant="outline" className="gap-1">
            <ShieldAlert className="h-3 w-3" />
            acts on the outside world
          </Badge>
        )}
      </div>
      <p className="text-muted-foreground mt-2 text-sm">{entry.description}</p>

      {entry.tools.length > 0 && (
        <ul className="mt-4 space-y-2">
          {entry.tools.map((tool) => (
            <li key={tool.id} className="border-border rounded-md border p-3">
              <p className="font-mono text-xs">{tool.name}</p>
              <p className="text-muted-foreground mt-1 text-xs">{tool.description}</p>
            </li>
          ))}
        </ul>
      )}

      <button
        type="button"
        disabled={disabled}
        onClick={onEnable}
        className="border-input hover:bg-accent mt-4 inline-flex items-center gap-2 rounded-md border px-3 py-1.5 text-sm transition-colors disabled:cursor-not-allowed disabled:opacity-60"
      >
        <Wrench className="h-3.5 w-3.5" />
        Give this agent {entry.name}
      </button>
    </div>
  );
}
