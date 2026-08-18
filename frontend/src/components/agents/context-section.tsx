"use client";

import { AlertTriangle } from "lucide-react";

import { CapabilityDetail } from "@/components/agents/capability-settings";
import { ContextGallery } from "@/components/agents/context-gallery";
import type { FieldProblem } from "@/lib/api-error";
import type { CapabilityBindingSpec, CapabilityCatalogEntry } from "@/types/agents";
import type { ContextFileSummary } from "@/types/providers";
import { useTranslations } from "next-intl";

interface ContextSectionProps {
  definition: CapabilityCatalogEntry | undefined;
  /** Bound, or what it would be if somebody switched it on - the workbench decides. */
  binding: CapabilityBindingSpec;
  /** The organization's files, to pick from. */
  files: ContextFileSummary[];
  /** How many it has, which may exceed what was fetched. */
  total: number;
  /** `spec.context_ids` - top level, never inside the capability's config. */
  selectedIds: string[];
  onToggleFile: (fileId: string) => void;
  onChange: (binding: CapabilityBindingSpec) => void;
  disabled?: boolean;
  configProblems?: readonly FieldProblem[];
}

/**
 * The Context capability, with the files it reads.
 *
 * Which files an agent gets used to be a card in the Skills tab, two tabs away
 * from the capability that reads them - so the panel a reader opens looking for
 * them offered a read-tool switch, an approval and two tool descriptions, and no
 * files. The switch is what makes them reach the model at all: injection happens
 * inside this capability, so a bound file with the capability off is not
 * "injected anyway", it is nothing.
 *
 * That is also why the files sit above the generated form rather than below it.
 * `expose_read_tool` is a question about *how* the model reaches them - and it is
 * still the schema's to draw, unlike the workspace and delegation panels, which
 * replace their form entirely.
 */
export function ContextSection({
  definition,
  binding,
  files,
  total,
  selectedIds,
  onToggleFile,
  onChange,
  disabled,
  configProblems,
}: ContextSectionProps) {
  const t = useTranslations("agents");

  // A deployment that did not register the capability has nothing to configure,
  // and an empty section reads as something that failed to load.
  if (!definition) return null;

  const enabled = binding.enabled === true;

  return (
    <div className="space-y-5">
      {/* The one state neither the switch nor the picker can say alone: the spec
          still carries the files, publish still checks they exist, and not one of
          them reaches a run. Silence here is how "why does it not know the
          glossary" becomes unanswerable. */}
      {!enabled && selectedIds.length > 0 && (
        <div className="flex items-start gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2.5">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
          <p className="text-xs">{t("contextOffButBound")}</p>
        </div>
      )}

      <section className="space-y-3">
        <div>
          <p className="text-sm font-medium">{t("contextFilesHeading")}</p>
          <p className="text-muted-foreground text-xs">{t("contextFilesDetail")}</p>
        </div>
        <ContextGallery
          files={files}
          total={total}
          selectedIds={selectedIds}
          onToggle={onToggleFile}
          disabled={disabled}
        />
      </section>

      <CapabilityDetail
        binding={binding}
        definition={definition}
        onChange={onChange}
        configProblems={configProblems}
        disabled={disabled}
      />
    </div>
  );
}
