"use client";

import { useId } from "react";
import { useTranslations } from "next-intl";
import { Checkbox, Label } from "@/components/ui";

const LABELS = {
  definition: "layerDefinition",
  skill_files: "layerSkillFiles",
  context_content: "layerContext",
  kb_documents: "layerOriginals",
  kb_parsed_text: "layerParsedText",
} as const;
export function ExportLayers({
  layers,
  selected,
  format,
  disabled,
  knowledgeBase,
  onChange,
}: {
  layers: string[];
  selected: string[];
  format: "yaml" | "json" | "zip";
  disabled: boolean;
  knowledgeBase: boolean;
  onChange: (layers: string[]) => void;
}) {
  const t = useTranslations("portability");
  const id = useId();
  const extra = layers.filter((layer) => layer !== "definition");
  if (!extra.length && !knowledgeBase) return null;
  return (
    <div className="ml-7 space-y-3 border-t pt-3">
      {extra.map((layer, index) => {
        const known = Object.prototype.hasOwnProperty.call(LABELS, layer);
        const label =
          layer === "skill_files"
            ? t("layerSkillFiles")
            : layer === "context_content"
              ? t("layerContext")
              : layer === "kb_documents"
                ? t("layerOriginals")
                : layer === "kb_parsed_text"
                  ? t("layerParsedText")
                  : t("unavailableLayer");
        return (
          <div key={layer} className="flex items-start gap-3">
            <Checkbox
              id={`${id}-${index}`}
              checked={format === "zip" && selected.includes(layer)}
              disabled={disabled || format !== "zip" || !known}
              onCheckedChange={(checked) =>
                onChange(checked ? [...selected, layer] : selected.filter((item) => item !== layer))
              }
            />
            <Label htmlFor={`${id}-${index}`} className="min-w-0 text-sm leading-5 font-normal">
              {label}
            </Label>
          </div>
        );
      })}
      {format !== "zip" && extra.length > 0 && (
        <p className="text-muted-foreground text-xs">{t("fileLayersZip")}</p>
      )}
      {knowledgeBase && <p className="text-muted-foreground text-xs">{t("indexExcluded")}</p>}
    </div>
  );
}
