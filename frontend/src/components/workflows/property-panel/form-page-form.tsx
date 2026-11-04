"use client";

import { useTranslations } from "next-intl";

import { FormSurface } from "../form-surface";
import { PublicForm } from "../public-form";
import { formPageOf } from "../form-page-config";
import { FormLinks } from "../form-links";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";
import { isRecord } from "./schema-model";
import {
  Input,
  Label,
  Textarea,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import type { NodeInstance, Uuid } from "@/lib/workflows/types";

/** The words a Form trigger's page shows, and the most each may hold - `FormTriggerConfig`. */
const PAGE_TEXT = [
  { key: "title", max: 120, long: false },
  { key: "description", max: 1000, long: true },
  { key: "submit_label", max: 40, long: false },
  { key: "success_message", max: 1000, long: true },
] as const;

interface FormPageFormProps {
  node: NodeInstance;
  disabled?: boolean;
  updateNodeConfig: (nodeId: Uuid, config: Record<string, unknown>) => void;
}

/**
 * The words on a Form trigger's public page: its title and description, the
 * button, and what it says once the answers are in. A box left empty is taken
 * out of the configuration, so the page falls back to its default wording
 * rather than to a blank heading.
 */
export function FormPageForm({ node, disabled, updateNodeConfig }: FormPageFormProps) {
  const t = useTranslations("workflows.formPage");
  const workflowId = useWorkflowEditorStore((state) => state.workflowId);
  const isDirty = useWorkflowEditorStore((state) => state.isDirty);
  const appearance = isRecord(node.config.appearance) ? node.config.appearance : {};
  const page = formPageOf(node.config, {
    title: t("title.placeholder"),
    submit: t("submit_label.placeholder"),
  });
  const setAppearance = (key: string, value: string) =>
    updateNodeConfig(node.id, {
      ...node.config,
      appearance: { ...appearance, [key]: value },
    });

  const write = (key: string, value: string) => {
    const { [key]: _dropped, ...rest } = node.config;
    updateNodeConfig(node.id, value === "" ? rest : { ...rest, [key]: value });
  };

  return (
    <section className="space-y-5">
      {workflowId && (
        <FormLinks workflowId={workflowId} entryId={node.id} saving={isDirty} canTest={!disabled} />
      )}
      {PAGE_TEXT.map(({ key, max, long }) => {
        const id = `form-page-${key}`;
        const value = typeof node.config[key] === "string" ? String(node.config[key]) : "";
        const Field = long ? Textarea : Input;
        return (
          <div key={key} className="space-y-1.5">
            <Label htmlFor={id}>{t(`${key}.label`)}</Label>
            <Field
              id={id}
              value={value}
              maxLength={max}
              disabled={disabled}
              placeholder={t(`${key}.placeholder`)}
              onChange={(event) => write(key, event.target.value)}
            />
          </div>
        );
      })}
      <div className="space-y-4 rounded-xl border p-4">
        <h3 className="text-sm font-medium">{t("appearance")}</h3>
        <div className="space-y-2">
          <Label htmlFor="form-accent">{t("accent")}</Label>
          <Input
            type="color"
            id="form-accent"
            className="h-10 w-16 p-1"
            disabled={disabled}
            value={typeof appearance.accent === "string" ? appearance.accent : "#52525b"}
            onChange={(event) => setAppearance("accent", event.target.value)}
          />
        </div>
        {(["width", "layout"] as const).map((key) => (
          <div className="space-y-2" key={key}>
            <Label htmlFor={`form-${key}`}>{t(key)}</Label>
            <Select
              disabled={disabled}
              value={String(appearance[key] ?? (key === "width" ? "standard" : "card"))}
              onValueChange={(value) => setAppearance(key, value)}
            >
              <SelectTrigger id={`form-${key}`}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {(key === "width" ? ["standard", "wide"] : ["card", "plain"]).map((value) => (
                  <SelectItem key={value} value={value}>
                    {t(value)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        ))}
      </div>
      <details className="rounded-xl border">
        <summary className="cursor-pointer p-4 text-sm font-medium">{t("preview")}</summary>
        <div className="bg-muted/20 p-4">
          <FormSurface appearance={page.appearance} preview>
            <PublicForm page={page} preview />
          </FormSurface>
        </div>
      </details>
    </section>
  );
}
