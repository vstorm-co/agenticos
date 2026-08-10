"use client";

import { Check, Database } from "lucide-react";
import { useTranslations } from "next-intl";

import { Input, Label } from "@/components/ui";
import { BrandIcon, connectorBrand } from "@/components/icons/brand-icon";
import type { SyncSourceRead } from "@/lib/rag-api";
import { cn } from "@/lib/utils";

export function CloneStep({
  integrations,
  cloneSourceId,
  setCloneSourceId,
  cloneName,
  setCloneName,
}: {
  integrations: SyncSourceRead[];
  cloneSourceId: string;
  setCloneSourceId: (id: string) => void;
  cloneName: string;
  setCloneName: (name: string) => void;
}) {
  const t = useTranslations("rag");
  return (
    <div className="space-y-5">
      <p className="text-foreground/65 text-sm">{t("pickExistingOrgIntegration")}</p>
      <div className="space-y-2">
        <Label className="text-foreground/80 text-xs font-medium tracking-wider uppercase">
          {t("orgIntegrations")}
        </Label>
        <div className="space-y-2">
          {integrations.map((src) => {
            const isSelected = cloneSourceId === src.id;
            const brand = connectorBrand(src.connector_type);
            return (
              <button
                key={src.id}
                type="button"
                onClick={() => setCloneSourceId(src.id)}
                className={cn(
                  "flex w-full items-center gap-3 rounded-xl border p-3.5 text-left transition-colors",
                  isSelected
                    ? "border-brand bg-brand/[0.06]"
                    : "border-foreground/10 bg-card hover:border-foreground/30",
                )}
              >
                <span
                  className={cn(
                    "flex h-9 w-9 shrink-0 items-center justify-center rounded-full",
                    isSelected
                      ? "bg-brand text-brand-foreground"
                      : "bg-foreground/8 text-foreground",
                  )}
                >
                  {brand ? (
                    <BrandIcon name={brand} className="h-4 w-4" aria-hidden />
                  ) : (
                    <Database className="h-4 w-4" />
                  )}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-foreground text-sm font-semibold">{src.name}</p>
                  <p className="text-foreground/55 font-mono text-[10px] tracking-wider uppercase">
                    {src.connector_type}
                    {src.collection_name ? ` · ${src.collection_name}` : " · unassigned"}
                  </p>
                </div>
                {isSelected && <Check className="text-brand h-4 w-4 shrink-0" />}
              </button>
            );
          })}
        </div>
      </div>

      {cloneSourceId && (
        <div className="space-y-1.5">
          <Label
            htmlFor="clone-name"
            className="text-foreground/80 text-xs font-medium tracking-wider uppercase"
          >
            {t("nameKbAposS")}
          </Label>
          <Input
            id="clone-name"
            placeholder={t("leaveEmptyAutoGenerate")}
            value={cloneName}
            onChange={(e) => setCloneName(e.target.value)}
            className="h-10 rounded-xl"
          />
        </div>
      )}
    </div>
  );
}
