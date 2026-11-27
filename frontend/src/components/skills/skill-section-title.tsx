"use client";

import {
  Building2,
  CircleDashed,
  Library,
  Lock,
  Package,
  PencilLine,
  Tag,
  UserRound,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useTranslations } from "next-intl";

import { AgentAvatar } from "@/components/agents/agent-avatar";
import type { SkillSection, SkillSectionKind } from "@/types/providers";
import { categoryLabel } from "./category-input";
import { IndustryIcon } from "./industry-icon";

const ICON_CLASS = "text-muted-foreground h-4 w-4 shrink-0";

const KIND_ICONS: Record<SkillSectionKind, LucideIcon> = {
  agent: UserRound,
  drafted: PencilLine,
  unused: CircleDashed,
  org: Building2,
  private: Lock,
  platform: Package,
  gallery: Library,
  category: Tag,
  uncategorized: Tag,
};

/** What a section is called, with its icon - or its agent's face - and its count. */
export function SkillSectionTitle({ section }: { section: SkillSection }) {
  const t = useTranslations("pages.skills");
  const tGallery = useTranslations("skills.gallery");
  const { agent, industry, category, kind } = section;

  const KindIcon = KIND_ICONS[kind];
  const title = agent
    ? agent.name
    : industry
      ? t("section.gallery", { industry: tGallery(`industry.${industry}`) })
      : category
        ? categoryLabel(category)
        : t(`section.${kind}`);

  return (
    <span className="inline-flex max-w-[calc(100%-1.5rem)] min-w-0 items-center gap-2 align-middle">
      {agent ? (
        <AgentAvatar
          agentId={agent.id}
          slug={agent.slug ?? agent.id}
          hasAvatar={agent.has_avatar}
          colorSlot={agent.avatar_color}
          size="sm"
          className="h-6 w-6"
        />
      ) : industry ? (
        <IndustryIcon id={industry} className={ICON_CLASS} strokeWidth={1.75} aria-hidden />
      ) : (
        <KindIcon className={ICON_CLASS} strokeWidth={1.75} aria-hidden />
      )}
      <span className="text-foreground truncate text-sm font-medium">{title}</span>
      <span className="text-muted-foreground shrink-0 text-xs font-normal">
        {t("skillCount", { count: section.count })}
      </span>
    </span>
  );
}
