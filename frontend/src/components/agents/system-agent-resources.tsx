"use client";

import { useTranslations } from "next-intl";

import { CapabilityResources, type AgentResources } from "@/components/agents/capability-resources";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui";
import { CONTEXT_ID, SKILLS_ID } from "@/lib/agent-spec";
import type { CapabilityBindingSpec, SystemAgentKind } from "@/types/agents";

/**
 * The standing text a system agent knows: its context files and, for every kind
 * but the classifier, its skills.
 *
 * Its page has no Toolbox, where an ordinary agent picks them in the panel of the
 * capability that reads each. These are those panels' own pickers, and the page
 * writes a pick the way the Toolbox does: the capability is bound with the first
 * file or skill and dropped with the last, so there is no switch to forget here.
 */
export function SystemAgentResources({
  kind,
  capabilities,
  resources,
  disabled,
}: {
  kind: SystemAgentKind;
  capabilities: CapabilityBindingSpec[];
  resources: AgentResources;
  disabled: boolean;
}) {
  const t = useTranslations("agents");
  const bound = (id: string) =>
    capabilities.some((binding) => binding.id === id && binding.enabled);
  const skills = kind !== "classifier";
  const context = sharedOnly(resources.contextFiles, resources.contextTotal, resources.contextIds);
  const skill = sharedOnly(resources.skills, resources.skillTotal, resources.skillIds);
  const offered: AgentResources = {
    ...resources,
    contextFiles: context.items,
    contextTotal: context.total,
    skills: skill.items,
    skillTotal: skill.total,
  };

  return (
    <Card>
      {/* The header, not the card: the galleries under it can run past the
          bottom of the screen, and a spotlight on all of it lights nothing. */}
      <CardHeader data-tour="agent-system-resources">
        <CardTitle>{t("systemAgentResources", { skills: String(skills) })}</CardTitle>
        <CardDescription>{t("systemAgentResourcesHelp")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        <section className="space-y-3">
          <h3 className="text-sm font-medium">{t("contextFilesHeading")}</h3>
          <CapabilityResources
            capabilityId={CONTEXT_ID}
            enabled={bound(CONTEXT_ID)}
            resources={offered}
            disabled={disabled}
          />
        </section>
        {skills && (
          <section className="space-y-3">
            <h3 className="text-sm font-medium">{t("skillsHeading")}</h3>
            <CapabilityResources
              capabilityId={SKILLS_ID}
              enabled={bound(SKILLS_ID)}
              resources={offered}
              disabled={disabled}
            />
          </section>
        )}
      </CardContent>
    </Card>
  );
}

/**
 * What a system agent may be given out of `items`: only what is shared with the
 * whole organization, since its publish refuses anything narrower - plus what it
 * already holds, so a pick made before that can still be taken off.
 *
 * `total` follows: the gallery names a chosen id it does not list as deleted only
 * while it holds the whole set, which the narrowed list still is when nothing was
 * left unfetched.
 */
function sharedOnly<T extends { id: string; visibility: string }>(
  items: T[],
  total: number,
  chosen: string[],
): { items: T[]; total: number } {
  const kept = items.filter((item) => item.visibility === "org" || chosen.includes(item.id));
  return { items: kept, total: items.length >= total ? kept.length : total };
}
