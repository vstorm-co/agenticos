"use client";

import { useMemo, useState } from "react";
import type { ReactNode } from "react";

import { CapabilityDetail } from "@/components/agents/capability-settings";
import { ImageGenerationSection } from "@/components/agents/image-generation-section";
import { TextToSpeechSection } from "@/components/agents/text-to-speech-section";
import { VideoGenerationSection } from "@/components/agents/video-generation-section";
import {
  CapabilityResources,
  resourceTabKey,
  type AgentResources,
} from "@/components/agents/capability-resources";
import { SubagentsSection } from "@/components/agents/subagents-section";
import { WorkspaceSection } from "@/components/agents/workspace-section";
import { SearchInput } from "@/components/ui";
import { CapabilityGallery } from "@/components/agents/capability-art/capability-gallery";
import { ClearAgentMemory } from "@/components/memory/clear-agent-memory";
import {
  IMAGE_GENERATION_ID,
  MEMORY_FILES_ID,
  MEMORY_MEM0_ID,
  SANDBOX_ID,
  SUBAGENTS_ID,
  TEXT_TO_SPEECH_ID,
  VIDEO_GENERATION_ID,
  unboundBinding,
} from "@/lib/agent-spec";
import type { FieldProblem } from "@/lib/api-error";
import type {
  CapabilityBindingSpec,
  CapabilityCatalogEntry,
  ExternalAgentRef,
  SubagentRef,
} from "@/types/agents";
import { contextSettings } from "@/lib/context-settings";
import { useTranslations } from "next-intl";

/**
 * Capabilities that tune how a run is carried rather than what the agent can do.
 *
 * Kept below the rest, folded, because each one answers a problem somebody meets
 * only after an agent is working - a long conversation, a huge tool result, dozens
 * of MCP tools - and a list that opens on them reads as a list of things to
 * understand before starting (#2070).
 */
const ADVANCED_CAPABILITIES: ReadonlySet<string> = new Set([
  "compaction",
  "media",
  "system_reminders",
  "tool_output_limits",
  "tool_search",
]);
const ADVANCED = "advanced";

interface CapabilityWorkbenchProps {
  /**
   * Which agent's capabilities these are.
   *
   * Only one panel needs it - memory, whose notes are cleared from inside the
   * capability that keeps them, because there is no browsing surface for them
   * anywhere else (#1470). Everything else here edits a spec and needs no id.
   */
  agentId: string;
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
  /** `spec.external_agents`, the remote A2A delegates, for the same reason (#2092). */
  externalAgents: ExternalAgentRef[];
  onExternalAgentsChange: (externalAgents: ExternalAgentRef[]) => void;
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
 * Cards that open their settings in a panel, rather than a grid of checkboxes
 * over a pile of settings cards. The pile was the problem: switching on five
 * capabilities produced five configuration panels stacked below the grid, each one separated from the
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
  agentId,
  catalog,
  selected,
  onToggle,
  onChange,
  subagents,
  onSubagentsChange,
  externalAgents,
  onExternalAgentsChange,
  resources,
  modelProfileId,
  disabled,
  configProblems,
}: CapabilityWorkbenchProps) {
  const t = useTranslations("agents");
  const tc = useTranslations("capabilityCategories");
  const enabled = new Set(selected.filter((binding) => binding.enabled).map((b) => b.id));
  // Which card's settings panel is open.
  const [openedId, setOpenedId] = useState<string | null>(null);

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
    const groupOf = (entry: CapabilityCatalogEntry) =>
      ADVANCED_CAPABILITIES.has(entry.id) ? ADVANCED : entry.category;
    const names = [...new Set(matching.map(groupOf))].filter((name) => name !== ADVANCED).sort();
    if (matching.some((entry) => groupOf(entry) === ADVANCED)) names.push(ADVANCED);
    return names.map((name) => ({
      name,
      entries: matching.filter((entry) => groupOf(entry) === name),
    }));
  }, [catalog, query]);

  const focused = catalog.find((entry) => entry.id === openedId);
  const bound = selected.find((entry) => entry.id === focused?.id);
  const isOn = focused !== undefined && enabled.has(focused.id);

  if (catalog.length === 0) return null;

  // No scroller of its own: the page is the one scrollbar a reader should meet,
  // and a panel holding a gallery of collections is taller than any frame worth
  // fixing.
  const detail = (
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
          ) : focused.id === TEXT_TO_SPEECH_ID ? (
            <TextToSpeechSection
              definition={focused}
              binding={bound ?? unboundBinding(focused.id)}
              onToggleEnabled={() => onToggle(focused.id)}
              onChange={onChange}
              configProblems={configProblems}
              disabled={disabled || !isOn}
              readOnly={disabled}
            />
          ) : focused.id === VIDEO_GENERATION_ID ? (
            <VideoGenerationSection
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
              externalAgents={externalAgents}
              onExternalAgentsChange={onExternalAgentsChange}
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
                  fileSettings={contextSettings(bound?.config.file_settings)}
                  onFileSettingsChange={
                    bound === undefined
                      ? undefined
                      : (file_settings) =>
                          onChange({
                            ...bound,
                            config: { ...bound.config, file_settings },
                          })
                  }
                  capabilityId={focused.id}
                  enabled={isOn}
                  resources={resources}
                  disabled={disabled || !isOn}
                />
              ))}
              // The one action on this panel that is not configuration: the
              // agent's notes are emptied from inside the capability that keeps
              // them, because nothing anywhere else in the console reads or
              // writes them.
              settingsFooter={
                focused.id === MEMORY_FILES_ID && isOn ? (
                  <ClearAgentMemory
                    agentId={agentId}
                    usesMem0={selected.some(
                      (binding) => binding.id === MEMORY_MEM0_ID && binding.enabled !== false,
                    )}
                    disabled={disabled}
                  />
                ) : undefined
              }
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
  );

  // A shelf of illustrated cards per category; a card's settings open in a
  // panel beside the page rather than below a list.
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <SearchInput
          value={query}
          onChange={setQuery}
          placeholder={t("searchCapabilities")}
          className="w-full sm:w-72"
        />
      </div>
      {categories.length === 0 ? (
        <p className="text-muted-foreground px-1 py-6 text-sm">
          {t("noCapabilityOrToolMatches", { query })}
        </p>
      ) : (
        <CapabilityGallery
          shelves={categories.map((category) => ({
            ...category,
            // A category the console has no words for yet - one added in
            // Python first - keeps the registry's own. The key is the
            // registry's, so it is read as a pattern over the namespace.
            label: tc.has(`${category.name}`) ? tc(`${category.name}`) : category.name,
          }))}
          enabled={enabled}
          openedId={openedId}
          disabled={disabled}
          onOpen={setOpenedId}
          onClose={() => setOpenedId(null)}
          onToggle={onToggle}
          detail={detail}
        />
      )}
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
