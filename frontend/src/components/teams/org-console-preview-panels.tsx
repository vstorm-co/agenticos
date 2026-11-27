"use client";

import { useTranslations } from "next-intl";
import { previewCatalogPolicies } from "@/lib/console-role-preview";
import { resolveEffectiveLayout } from "@/lib/dashboard/preference";
import { resolveAudience, viewLayout, visibleSections } from "@/lib/dashboard/layouts";
import type { ConsolePresentation, ConsoleRoleDefaults } from "@/lib/console-experience-api";
import type { OrgRole } from "@/types/organization";
import type { Permission } from "@/types/permissions";

export function OrganizationConsolePreviewPanels({
  role,
  defaults,
  presentation,
  can,
  managesMcp,
  managesSkills,
}: {
  role: OrgRole;
  defaults: ConsoleRoleDefaults | undefined;
  presentation: ConsolePresentation;
  can: (permission: Permission) => boolean;
  managesMcp: boolean;
  managesSkills: boolean;
}) {
  const t = useTranslations("consoleExperience.rolePreview");
  const copy = useTranslations("consoleExperience.presentation");
  const catalogs = useTranslations("consoleExperience.catalogs");
  const dashboard = useTranslations("dashboard");
  const audience = resolveAudience(role, false);
  const layout =
    defaults?.dashboard == null
      ? viewLayout("me", audience)
      : resolveEffectiveLayout(audience, defaults.dashboard.entries);
  const sections = visibleSections(layout, can, false);
  return (
    <div className="min-w-0 space-y-6">
      <section aria-label={t("dashboard")} className="space-y-3">
        <h3 className="font-medium">{t("dashboard")}</h3>
        {sections.length === 0 && (
          <p className="text-muted-foreground text-sm">{t("emptyDashboard")}</p>
        )}
        {sections.map((section) => (
          <div key={section.id} className="space-y-2">
            {section.title && (
              <h4 className="text-muted-foreground text-xs font-medium">{section.title}</h4>
            )}
            <div className="grid gap-3 @min-[30rem]:grid-cols-2">
              {section.entries.map((entry, index) => (
                <article
                  key={`${entry.widget}-${index}`}
                  className="bg-card min-w-0 rounded-xl border p-4"
                >
                  <h4 className="text-sm font-medium">
                    {dashboard(entry.titleKey ?? `widgets.${entry.widget}.title`)}
                  </h4>
                  <div aria-hidden className="mt-4 space-y-2">
                    <div className="bg-muted h-2 w-1/3 rounded" />
                    <div className="bg-muted h-2 w-2/3 rounded" />
                  </div>
                </article>
              ))}
            </div>
          </div>
        ))}
      </section>
      <section aria-label={t("catalogs")} className="space-y-3">
        <h3 className="font-medium">{t("catalogs")}</h3>
        <dl className="grid gap-3 @min-[30rem]:grid-cols-2">
          {(["mcp_gallery", "skill_gallery"] as const).map((kind) => {
            const manages = kind === "mcp_gallery" ? managesMcp : managesSkills;
            const permitted = can(kind === "mcp_gallery" ? "agents:view" : "skills:view");
            const policy = previewCatalogPolicies([
              kind === "mcp_gallery"
                ? presentation.available_mcp_gallery
                : presentation.available_skill_gallery,
              manages ? null : defaults?.[kind],
            ]);
            return (
              <div key={kind} className="min-w-0 rounded-xl border p-4">
                <dt className="text-sm font-medium">{catalogs(kind)}</dt>
                <dd className="text-muted-foreground mt-2 space-y-1 text-sm">
                  <p>
                    {!permitted
                      ? t("unavailable")
                      : policy.approvedLimit === null
                        ? t("wholeCatalog")
                        : t("approvedLimit", { count: policy.approvedLimit })}
                  </p>
                  {permitted && policy.availableOnly && <p>{t(`${kind}Available`)}</p>}
                </dd>
              </div>
            );
          })}
        </dl>
      </section>
      <section aria-label={copy("noticesTitle")} className="space-y-3">
        <h3 className="font-medium">{copy("noticesTitle")}</h3>
        <dl className="divide-y rounded-xl border px-4">
          {(["desktop_install_prompt", "product_notices"] as const).map((kind) => (
            <div key={kind} className="flex min-w-0 flex-wrap justify-between gap-2 py-3 text-sm">
              <dt>{copy(kind)}</dt>
              <dd className="text-muted-foreground">
                {t(
                  presentation.notices_available[kind] !== false &&
                    presentation.organization_notices[kind] !== false
                    ? "shown"
                    : "hidden",
                )}
              </dd>
            </div>
          ))}
        </dl>
      </section>
    </div>
  );
}
