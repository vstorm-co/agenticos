"use client";

import { useMemo, useState } from "react";
import { ShieldAlert } from "lucide-react";

import { CapabilityDetail } from "@/components/agents/capability-settings";
import { WorkspaceSection } from "@/components/agents/workspace-section";
import { SearchInput, Switch } from "@/components/ui";
import { SANDBOX_ID } from "@/lib/agent-spec";
import { cn } from "@/lib/utils";
import type { CapabilityBindingSpec, CapabilityCatalogEntry } from "@/types/agents";
import { useTranslations } from "next-intl";

interface CapabilityWorkbenchProps {
  catalog: CapabilityCatalogEntry[];
  selected: CapabilityBindingSpec[];
  onToggle: (capabilityId: string) => void;
  onChange: (binding: CapabilityBindingSpec) => void;
  disabled?: boolean;
}

/**
 * The binding a capability would get if somebody switched it on.
 *
 * Exists so the detail panel has something to render for a capability nobody has
 * granted yet. Deliberately the same shape `withCapability` creates, and
 * deliberately not passed to `onChange`: it is what the panel *would* be
 * configuring, shown so the decision can be made on the real thing.
 */
function unboundBinding(capabilityId: string): CapabilityBindingSpec {
  return {
    id: capabilityId,
    config: {},
    approval: "default",
    tool_approval: {},
    tool_overrides: {},
    secret_id: null,
    enabled: false,
  };
}

/**
 * Choose what an agent can do, and configure the one you are looking at.
 *
 * Master-detail rather than a grid of checkboxes over a pile of settings cards.
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
 *
 * The panel shows the same thing either way. There used to be a second,
 * smaller rendering for capabilities nobody had granted - tool names and
 * one-line descriptions, no arguments, no approval, no configuration schema -
 * which meant the way to find out what granting a capability actually involved
 * was to grant it. Now the detail is the detail, with its controls inert until
 * the capability is on: reading is still not granting, but the thing being read
 * is no longer an abridgement.
 */
export function CapabilityWorkbench({
  catalog,
  selected,
  onToggle,
  onChange,
  disabled,
}: CapabilityWorkbenchProps) {
  const t = useTranslations("agents");
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
  const bound = selected.find((entry) => entry.id === focused?.id);
  const isOn = focused !== undefined && enabled.has(focused.id);

  if (catalog.length === 0) return null;

  return (
    // One frame, one height, whichever capability is showing. The page used to be
    // as tall as whatever was selected: opening the workspace - the tallest panel
    // by far - and then clicking a short one left the document scrolled past its
    // own content, hundreds of pixels of nothing below the MCP section. Both
    // columns now scroll inside a fixed pane, so choosing a capability moves
    // nothing on the page around it.
    <div className="grid gap-4 lg:h-[36rem] lg:grid-cols-[minmax(0,18rem)_minmax(0,1fr)]">
      <div className="flex min-h-0 flex-col gap-3">
        {catalog.length > 8 && (
          <SearchInput
            value={query}
            onChange={setQuery}
            placeholder={t("searchCapabilities")}
            className="w-full sm:w-full"
          />
        )}

        <div className="min-h-0 space-y-4 lg:flex-1 lg:overflow-y-auto lg:pr-1">
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
                  // "7 tools" is the least useful thing to say about the
                  // workspace in a list: which backend it runs is what somebody
                  // is scanning for, and it is the only capability whose row can
                  // answer that.
                  subtitle={
                    entry.id === SANDBOX_ID
                      ? backendLabel(
                          selected.find((binding) => binding.id === entry.id),
                          enabled.has(entry.id),
                        )
                      : undefined
                  }
                  onFocus={() => setFocusedId(entry.id)}
                  onToggle={() => onToggle(entry.id)}
                />
              ))}
            </div>
          ))}
        </div>
      </div>

      {/* Scrolls in its own pane rather than lengthening the page. Without this
          the workspace panel - the one capability with tiles, two selects, a
          warning and a nested settings form - set the height of the whole
          Builder. */}
      <div className="min-h-0 min-w-0 lg:overflow-y-auto lg:pr-1">
        {focused && (
          <div className="space-y-3">
            {/* The switch travels with the panel as well as sitting in the row.
                The list scrolls independently, so the capability being read can
                be off screen from the control that grants it. */}
            <div className="border-border bg-card flex flex-wrap items-center justify-between gap-3 rounded-xl border px-4 py-3">
              <div className="min-w-0">
                <p className="text-sm font-medium">
                  {isOn ? `${focused.name} is on` : `Give this agent ${focused.name}`}
                </p>
                <p className="text-muted-foreground mt-0.5 text-xs">
                  {isOn
                    ? "Everything below applies to this agent alone."
                    : "Read it here first - the settings below are what switching it on configures."}
                </p>
              </div>
              <Switch
                checked={isOn}
                disabled={disabled}
                // Named as the state of the capability on show, not as the
                // picker's own control above. Two switches doing the same thing
                // is fine; two switches answering to the same name is not - a
                // screen reader announces them identically and neither says
                // which capability it belongs to.
                aria-label={`${focused.name} enabled`}
                onCheckedChange={() => onToggle(focused.id)}
              />
            </div>

            {/* The workspace's configuration is a choice between three
                backends and who shares them, not a set of fields - and one of
                those scopes shares files between people, which a generated form
                cannot warn about. Enablement is still the switch above, the same
                one every capability has. */}
            {focused.id === SANDBOX_ID ? (
              <WorkspaceSection
                definition={focused}
                binding={bound}
                onChange={onChange}
                disabled={disabled || !isOn}
              />
            ) : (
              <CapabilityDetail
                binding={bound ?? unboundBinding(focused.id)}
                definition={focused}
                onChange={onChange}
                // A capability nobody granted has nothing to configure yet, so
                // its controls are shown at their real values and left inert.
                // The alternative - live controls writing to a binding that does
                // not exist - would make reading a capability grant it by
                // accident.
                disabled={disabled || !isOn}
              />
            )}
          </div>
        )}
      </div>
    </div>
  );
}

/** What the workspace row says it is, rather than how many tools it has. */
function backendLabel(binding: CapabilityBindingSpec | undefined, enabled: boolean): string {
  if (!enabled) return "no workspace";
  const backend = (binding?.config as { backend?: string } | undefined)?.backend ?? "state";
  // The kind of host - a container service or Daytona - belongs to the
  // connection rather than the spec, so the row says what the agent gets and not
  // where it runs. "Where" is on the connection, which the detail panel names.
  if (backend === "service") return "files and a shell";
  return "files, no shell";
}

function CapabilityRow({
  entry,
  enabled,
  focused,
  disabled,
  subtitle,
  onFocus,
  onToggle,
}: {
  entry: CapabilityCatalogEntry;
  enabled: boolean;
  focused: boolean;
  disabled?: boolean;
  subtitle?: string;
  onFocus: () => void;
  onToggle: () => void;
}) {
  const t = useTranslations("agents");
  return (
    <div
      className={cn(
        "flex items-start gap-2 rounded-lg border px-2 py-2 transition-colors",
        focused ? "border-foreground/25 bg-accent" : "hover:bg-accent/50 border-transparent",
      )}
    >
      <button
        type="button"
        onClick={onFocus}
        aria-current={focused ? "true" : undefined}
        className="min-w-0 flex-1 text-left"
      >
        <span className="flex flex-wrap items-center gap-1.5">
          <span className="text-sm font-medium">{entry.name}</span>
          {entry.side_effecting && (
            <ShieldAlert className="text-muted-foreground h-3 w-3" aria-label={t("actsWorld")} />
          )}
        </span>
        <span className="text-muted-foreground mt-0.5 block text-xs">
          {subtitle ??
            (entry.tools.length === 0
              ? "no tools - changes how it runs"
              : entry.tools.length === 1
                ? "1 tool"
                : `${entry.tools.length} tools`)}
        </span>
      </button>

      {/* Its own control, not the row. Reading what a capability offers must not
          be the same gesture as granting it - and a switch says "on or off",
          which is what this is, where a checkbox says "one of a set". */}
      <Switch
        checked={enabled}
        disabled={disabled}
        aria-label={`Give this agent ${entry.name}`}
        onCheckedChange={onToggle}
        className="mt-0.5 shrink-0"
      />
    </div>
  );
}
