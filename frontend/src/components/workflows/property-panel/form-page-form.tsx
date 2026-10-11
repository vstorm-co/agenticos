"use client";

import { useTranslations } from "next-intl";

import { Input, Label, Textarea } from "@/components/ui";
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

  const write = (key: string, value: string) => {
    const { [key]: _dropped, ...rest } = node.config;
    updateNodeConfig(node.id, value === "" ? rest : { ...rest, [key]: value });
  };

  return (
    <section className="space-y-3">
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
    </section>
  );
}
