"use client";

import { useTranslations } from "next-intl";

/**
 * The docked property panel — the seam the #1787 property-panel leaf fills.
 *
 * The leaf builds `node-form.tsx` here (resolving `$ref`, nested objects,
 * arrays-of-rows and discriminated unions over `schema-form.tsx`), wraps every
 * binding-aware leaf in `BindingField`, and shows the empty/multi-select states
 * and the validation problems list. It reads the selected node from the editor
 * store's `selection`.
 */
export function PropertyPanel() {
  const t = useTranslations("workflows");
  return (
    <section
      aria-label={t("panelTitle")}
      data-workflow-region="property-panel"
      className="border-border space-y-1 rounded-xl border p-4"
    >
      <h2 className="text-sm font-medium">{t("panelTitle")}</h2>
      <p className="text-muted-foreground text-xs">{t("panelEmpty")}</p>
    </section>
  );
}
