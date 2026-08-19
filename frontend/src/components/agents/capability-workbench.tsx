"use client";

import { useMemo, useState } from "react";
import type { ReactNode } from "react";
import { ShieldAlert } from "lucide-react";

import { CapabilityDetail } from "@/components/agents/capability-settings";
import { ImageGenerationSection } from "@/components/agents/image-generation-section";
import {
  CapabilityResources,
  resourceTabKey,
  type AgentResources,
} from "@/components/agents/capability-resources";
import { SubagentsSection } from "@/components/agents/subagents-section";
import { WorkspaceSection } from "@/components/agents/workspace-section";
import { SearchInput, Switch } from "@/components/ui";
import {
  IMAGE_GENERATION_ID,
  readSubagentsConfig,
  SANDBOX_ID,
  SUBAGENTS_ID,
  unboundBinding,
} from "@/lib/agent-spec";
import type { FieldProblem } from "@/lib/api-error";
import { cn } from "@/lib/utils";
import type { CapabilityBindingSpec, CapabilityCatalogEntry, SubagentRef } from "@/types/agents";
import { useTranslations } from "next-intl";

interface CapabilityWorkbenchProps {
  catalog: CapabilityCatalogEntry[];
  selected: CapabilityBindingSpec[];
  onToggle: (capabilityId: string) => void;
  onChange: (binding: CapabilityBindingSpec) => void;
  /**
   * `spec.subagents`, which delegation edits from inside its own panel.
   *
   * A capability whose configuration is partly *not* in its config blob is the
   * one thing that makes this workbench pass a slice of the spec through. The
   * references live top level because they are references to other rows, like
   * `collection_ids`, and that is what publish validation walks.
   */
  subagents: SubagentRef[];
  onSubagentsChange: (subagents: SubagentRef[]) => void;
  /**
   * What the organization owns and this agent may be given - context files,
   * collections, skills.
   *
   * Top level on the spec rather than inside a capability's config, the same
   * arrangement as `subagents`, so the panel that picks them is handed that slice
   * as well as the binding. One bundle rather than twelve props.
   */
  resources: AgentResources;
  /**
   * The agent's own model profile, handed to the delegation panel so promoting a
   * specialist that runs on "the same model as its parent" can resolve one.
   */
  modelProfileId: string | null;
  disabled?: boolean;
  /**
   * What the last publish attempt said about the inputs on these forms.
   *
   * A capability's configuration is generated from its schema, so a refusal
   * about one of its settings has an input to be shown on - which is the whole
   * reason `validate_spec` reports fields as well as sentences (#882).
   */
  configProblems?: readonly FieldProblem[];
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
  subagents,
  onSubagentsChange,
  resources,
  modelProfileId,
  disabled,
  configProblems,
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
    // The panel grows with what it holds; only the list is a bounded, scrolling
    // column. It was a fixed 36rem frame with *both* columns scrolling inside it,
    // for a reason that no longer holds: choosing a shorter capability was said to
    // leave "the document scrolled past its own content, hundreds of pixels of
    // nothing below the MCP section", and the browser in fact clamps that -
    // measured on this page, switching from the workspace panel at the bottom of
    // the page moves scrollTop 2080 -> 0, and paging the server catalog 2080 ->
    // 400, neither overshooting. What the frame did cost was real: a scrollbar
    // inside the page beside the page's own, which is what a picker in a panel now
    // meets every time, and 400px of dead card under a short panel.
    <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,18rem)_minmax(0,1fr)]">
      {/* Capped to the viewport rather than to 36rem. Sticky and 36rem tall left
          a void beside a long panel - measured 532px of empty gutter next to the
          image capability's 1108px panel - where a column the height of the
          screen is filled by the catalog itself. On a tall screen the whole list
          fits, so its own scrollbar stops appearing too. */}
      <div className="flex flex-col gap-3 lg:sticky lg:top-4 lg:max-h-[calc(100vh-8rem)]">
        {catalog.length > 8 && (
          <SearchInput
            value={query}
            onChange={setQuery}
            placeholder={t("searchCapabilities")}
            className="w-full sm:w-full"
          />
        )}

        {/* The one bounded column: a catalog of thirty has to stay reachable
            beside a long panel, so it is capped and scrolls, and the column is
            sticky so it does not leave with the page. */}
        <div className="min-h-0 scrollbar-thin space-y-4 lg:flex-1 lg:overflow-y-auto lg:pr-1">
          {categories.length === 0 && (
            <p className="text-muted-foreground px-1 py-6 text-sm">
              {t("noCapabilityOrToolMatches", { query })}
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
                      : entry.id === SUBAGENTS_ID
                        ? // Who it hands work to, which is the only thing about
                          // delegation worth scanning a list for. "10 tools" is
                          // true of every agent that has it.
                          t("delegateCount", {
                            count:
                              subagents.length +
                              readSubagentsConfig(
                                selected.find((binding) => binding.id === entry.id),
                              ).inline.length,
                          })
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
      {/* No scroller of its own: the page is the one scrollbar a reader should
          meet, and a panel holding a gallery of collections is taller than any
          frame worth fixing. */}
      <div className="min-w-0">
        {focused && (
          <div className="space-y-3">
            {/* The workspace's configuration is a choice between three
                backends and who shares them, not a set of fields - and one of
                those scopes shares files between people, which a generated form
                cannot warn about. Enablement is still the switch above, the same
                one every capability has. */}
            {focused.id === SANDBOX_ID ? (
              <WorkspaceSection
                definition={focused}
                binding={bound}
                onToggleEnabled={() => onToggle(focused.id)}
                onChange={onChange}
                disabled={disabled || !isOn}
                readOnly={disabled}
              />
            ) : /* Delegation is three decisions, only one of which is a set of
                  fields: a list of other agents pinned to versions, a list of
                  specialists that are not versioned at all, and the policy
                  bounding both. The pins are the reason - a delegate that has
                  moved on is stale, and staleness nothing surfaces is a bug
                  frozen in place under a published parent. */
            /* Which model draws is a provider and a model, not one string of a
               schema's making: OpenAI and Google each ship several image models
               and the server says which. */
            focused.id === IMAGE_GENERATION_ID ? (
              <ImageGenerationSection
                definition={focused}
                binding={bound ?? unboundBinding(focused.id)}
                onToggleEnabled={() => onToggle(focused.id)}
                onChange={onChange}
                configProblems={configProblems}
                disabled={disabled || !isOn}
                readOnly={disabled}
              />
            ) : focused.id === SUBAGENTS_ID ? (
              <SubagentsSection
                definition={focused}
                binding={bound}
                onToggleEnabled={() => onToggle(focused.id)}
                catalog={catalog}
                parentCapabilities={selected}
                parentModelProfileId={modelProfileId}
                subagents={subagents}
                onChange={onChange}
                onSubagentsChange={onSubagentsChange}
                disabled={disabled || !isOn}
                readOnly={disabled}
              />
            ) : (
              <CapabilityDetail
                binding={bound ?? unboundBinding(focused.id)}
                definition={focused}
                onChange={onChange}
                onToggleEnabled={() => onToggle(focused.id)}
                configProblems={configProblems}
                // What this capability reads of the organization's, where it
                // reads anything: the files, the collections, the skills. It gets
                // the first tab and the panel opens on it.
                resources={panelResources(focused.id, t, () => (
                  <CapabilityResources
                    capabilityId={focused.id}
                    enabled={isOn}
                    resources={resources}
                    disabled={disabled || !isOn}
                  />
                ))}
                // A capability nobody granted has nothing to configure yet, so
                // its controls are shown at their real values and left inert.
                // The alternative - live controls writing to a binding that does
                // not exist - would make reading a capability grant it by
                // accident.
                disabled={disabled || !isOn}
                readOnly={disabled}
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
      // Addressable per capability, because the walkthrough points at three of
      // these rows: what an agent may search, read and load is picked inside the
      // panel a row opens, and the row is the bounded thing a spotlight can sit
      // on. The panel itself only exists once one has been clicked.
      data-tour={`capability-${entry.id}`}
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
              ? t("noToolsChangesHow")
              : t("toolCount", { count: entry.tools.length }))}
        </span>
      </button>

      {/* Its own control, not the row. Reading what a capability offers must not
          be the same gesture as granting it - and a switch says "on or off",
          which is what this is, where a checkbox says "one of a set". */}
      <Switch
        checked={enabled}
        disabled={disabled}
        aria-label={t("giveThisAgent", { name: entry.name })}
        onCheckedChange={onToggle}
        className="mt-0.5 shrink-0"
      />
    </div>
  );
}

/**
 * The resources tab for one capability, or nothing where it has none.
 *
 * The label is a catalog key `capability-resources` answers with - a module
 * constant cannot translate - and the body is built lazily, so a capability with
 * no resources renders no picker rather than one that returns null.
 */
function panelResources(
  capabilityId: string,
  t: (key: string) => string,
  content: () => ReactNode,
): { label: string; content: ReactNode } | undefined {
  const key = resourceTabKey(capabilityId);
  return key === undefined ? undefined : { label: t(key), content: content() };
}
