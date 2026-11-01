"use client";

import { useState } from "react";
import { ArrowLeft, Database, FlaskConical, Workflow } from "lucide-react";
import { useTranslations } from "next-intl";
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui";
import { DIALOG_CANVAS, DIALOG_FILL, DIALOG_SCROLL_GUTTER } from "@/lib/dialog-sizes";
import { cn } from "@/lib/utils";
import { WORKFLOW_TEMPLATES } from "@/lib/workflows/templates";
import type { WorkflowCreateChoice } from "./workflow-create-dialog";

type Category = "automations" | "examples";

/** A separate template library, following the agent library's category-first layout. */
export function WorkflowTemplateDialog({
  open,
  onOpenChange,
  onChoose,
  canProvisionTables,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onChoose: (choice: WorkflowCreateChoice) => void;
  canProvisionTables: boolean;
}) {
  const t = useTranslations("pages.workflows");
  const [category, setCategory] = useState<Category | null>(null);
  const templates =
    category === "automations"
      ? (["publicApi", "markdownNotes"] as const).map((id) => ({
          id,
          graph: null,
          template_id: id,
        }))
      : WORKFLOW_TEMPLATES.map((template) => ({ ...template, template_id: undefined }));
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setCategory(null);
        onOpenChange(next);
      }}
    >
      <DialogContent className={cn(DIALOG_FILL, DIALOG_CANVAS)}>
        <DialogHeader>
          <DialogTitle>{t("templateLibrary")}</DialogTitle>
          <DialogDescription>{t("templateLibraryDescription")}</DialogDescription>
        </DialogHeader>
        <div className={cn("min-h-0 flex-1 overflow-y-auto", DIALOG_SCROLL_GUTTER)}>
          {category ? (
            <div className="space-y-5 p-1">
              <Button variant="ghost" onClick={() => setCategory(null)}>
                <ArrowLeft className="size-4" />
                {t("templateCategories")}
              </Button>
              <div className="grid items-stretch gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {templates.map((template) => (
                  <div key={template.id} className="flex flex-col gap-4 rounded-xl border p-5">
                    <Workflow className="text-muted-foreground size-8" aria-hidden />
                    <div className="flex-1 space-y-2">
                      <h3 className="font-semibold">{t(`templates.${template.id}.name`)}</h3>
                      <p className="text-muted-foreground text-sm">
                        {t(`templates.${template.id}.description`)}
                      </p>
                    </div>
                    <Button
                      variant="outline"
                      disabled={!!template.template_id && !canProvisionTables}
                      title={
                        template.template_id && !canProvisionTables
                          ? t("templatesNeedTables")
                          : undefined
                      }
                      onClick={() =>
                        onChoose({
                          name: t(`templates.${template.id}.name`),
                          description: t(`templates.${template.id}.description`),
                          graph: template.graph,
                          ...(template.template_id ? { template_id: template.template_id } : {}),
                        })
                      }
                    >
                      {t("useTemplate")}
                    </Button>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div className="grid gap-4 p-1 sm:grid-cols-2 lg:grid-cols-3">
              {(["automations", "examples"] as const).map((id) => {
                const Icon = id === "automations" ? Database : FlaskConical;
                return (
                  <button
                    type="button"
                    key={id}
                    onClick={() => setCategory(id)}
                    className="hover:bg-accent hover:border-foreground/30 flex flex-col items-center gap-3 rounded-lg border p-8 text-center transition-colors"
                  >
                    <Icon className="text-muted-foreground size-10" aria-hidden />
                    <span className="font-semibold">
                      {t(id === "automations" ? "automationsHeading" : "examplesHeading")}
                    </span>
                    <span className="text-muted-foreground text-sm">
                      {t("templateCount", {
                        count: id === "automations" ? 2 : WORKFLOW_TEMPLATES.length,
                      })}
                    </span>
                    <span className="text-muted-foreground text-sm">
                      {t(id === "automations" ? "automationCategoryHint" : "exampleCategoryHint")}
                    </span>
                  </button>
                );
              })}
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
