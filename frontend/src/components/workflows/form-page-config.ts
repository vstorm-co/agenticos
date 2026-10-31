import { inputFieldsOf } from "@/lib/workflows/input-fields";
import type { PublicFormPage } from "./public-form";
import { isRecord } from "./property-panel/schema-model";

/** Project only supported appearance values from an editable, possibly incomplete draft. */
export function formPageOf(
  config: Record<string, unknown>,
  defaults: { title: string; submit: string },
): PublicFormPage {
  const appearance = isRecord(config.appearance) ? config.appearance : {};
  return {
    title: typeof config.title === "string" && config.title.trim() ? config.title : defaults.title,
    description: typeof config.description === "string" ? config.description : null,
    submit_label:
      typeof config.submit_label === "string" && config.submit_label.trim()
        ? config.submit_label
        : defaults.submit,
    fields: inputFieldsOf(config),
    appearance: {
      accent: typeof appearance.accent === "string" ? appearance.accent : null,
      width: appearance.width === "wide" ? "wide" : "standard",
      layout: appearance.layout === "plain" ? "plain" : "card",
    },
  };
}
