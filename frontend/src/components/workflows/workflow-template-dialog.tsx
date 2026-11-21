"use client";

import { useState } from "react";
import { ArrowLeft, Database, FlaskConical } from "lucide-react";
import { WorkflowIcon as Workflow } from "@/components/icons/product-icons";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui";
import {
  TemplateCategoryButton,
  TemplateLibraryDialog,
  TemplateLibraryItem,
} from "@/components/templates/template-library";
import { DIALOG_SCROLL_GUTTER } from "@/lib/dialog-sizes";
import { cn } from "@/lib/utils";
import { WORKFLOW_TEMPLATES } from "@/lib/workflows/templates";
import type { WorkflowCreateChoice } from "./workflow-create-dialog";

type Category = "automations" | "examples";

/** The same category-to-library composition as agents, with workflow admission unchanged. */
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
      ? (["publicApi", "markdownNotes", "awaitReply"] as const).map((id) => ({
          id,
          graph: null,
          template_id: id,
        }))
      : WORKFLOW_TEMPLATES.map((template) => ({ ...template, template_id: undefined }));
  const categoryTitle = category === "automations" ? "automationsHeading" : "examplesHeading";
  return (
    <TemplateLibraryDialog
      open={open}
      detail={category !== null}
      onOpenChange={(next) => {
        setCategory(null);
        onOpenChange(next);
      }}
      title={category ? t(categoryTitle) : t("templateLibrary")}
      description={
        category
          ? t(category === "automations" ? "automationCategoryHint" : "exampleCategoryHint")
          : t("templateLibraryDescription")
      }
    >
      {category ? (
        <>
          <Button
            variant="ghost"
            size="sm"
            className="self-start"
            onClick={() => setCategory(null)}
          >
            <ArrowLeft className="size-4" aria-hidden />
            {t("templateCategories")}
          </Button>
          <div className={cn("min-h-0 flex-1 space-y-3 overflow-y-auto p-1", DIALOG_SCROLL_GUTTER)}>
            {templates.map((template) => {
              const blocked =
                !!template.template_id && template.id !== "awaitReply" && !canProvisionTables;
              return (
                <TemplateLibraryItem key={template.id}>
                  <Workflow className="text-muted-foreground size-9 shrink-0" aria-hidden />
                  <div className="min-w-0 space-y-2">
                    <h3 className="font-medium">{t(`templates.${template.id}.name`)}</h3>
                    <p className="text-muted-foreground text-sm">
                      {t(`templates.${template.id}.description`)}
                    </p>
                    {blocked && (
                      <p className="text-muted-foreground text-xs">{t("templatesNeedTables")}</p>
                    )}
                  </div>
                  <Button
                    variant="outline"
                    size="sm"
                    className="col-start-2 w-fit shrink-0 sm:col-start-auto"
                    disabled={blocked}
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
                </TemplateLibraryItem>
              );
            })}
          </div>
        </>
      ) : (
        <div className={cn("min-h-0 flex-1 overflow-y-auto", DIALOG_SCROLL_GUTTER)}>
          <div className="grid gap-4 p-1 sm:grid-cols-2">
            {(["automations", "examples"] as const).map((id) => (
              <TemplateCategoryButton
                key={id}
                icon={id === "automations" ? Database : FlaskConical}
                title={t(id === "automations" ? "automationsHeading" : "examplesHeading")}
                count={t("templateCount", {
                  count: id === "automations" ? 3 : WORKFLOW_TEMPLATES.length,
                })}
                description={t(
                  id === "automations" ? "automationCategoryHint" : "exampleCategoryHint",
                )}
                onClick={() => setCategory(id)}
              />
            ))}
          </div>
        </div>
      )}
    </TemplateLibraryDialog>
  );
}
