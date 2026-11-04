"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";

import { schemaDependents, type SchemaDependent } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";

/** The message key for each kind a dependency checker reports. */
const KIND_KEYS: Record<string, "workflow" | "view" | "trigger"> = {
  workflow: "workflow",
  table_view: "view",
  table_trigger: "trigger",
};

/**
 * What a refused schema change or archive named as still using the column, so
 * the person knows what to change first. Renders nothing for any other failure.
 */
export function SchemaDependents({ error }: { error: unknown }) {
  const t = useTranslations("tables.dependents");
  const dependents = schemaDependents(error);
  if (dependents === null) return null;

  function label(dependent: SchemaDependent) {
    if (dependent.name === null) return <span className="italic">{t("hidden")}</span>;
    if (dependent.kind !== "workflow") return <span>{dependent.name}</span>;
    return (
      <Link
        href={ROUTES.WORKFLOW_DETAIL(dependent.id)}
        className="font-medium underline-offset-2 hover:underline"
      >
        {dependent.name}
      </Link>
    );
  }

  return (
    <div role="alert" className="space-y-1.5 text-sm">
      <p className="text-destructive">{t("lead")}</p>
      <ul className="space-y-1">
        {dependents.map((dependent) => (
          <li key={`${dependent.kind}:${dependent.id}`} className="flex items-baseline gap-2">
            <span className="text-muted-foreground w-24 shrink-0 text-xs">
              {t(`kind.${KIND_KEYS[dependent.kind] ?? "other"}`)}
            </span>
            {label(dependent)}
          </li>
        ))}
      </ul>
    </div>
  );
}
