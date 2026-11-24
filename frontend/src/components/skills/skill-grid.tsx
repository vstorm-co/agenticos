"use client";

import { SkillCard } from "./skill-card";
import type { SkillSummary } from "@/types/providers";

/** Skills as cards, in the grid every layout of the Skills page draws. */
export function SkillGrid({
  skills,
  onOpen,
}: {
  skills: SkillSummary[];
  onOpen: (id: string) => void;
}) {
  return (
    <div className="rise-in grid grid-cols-1 items-stretch gap-3 md:grid-cols-2 xl:grid-cols-3">
      {skills.map((skill) => (
        <SkillCard key={skill.id} skill={skill} onOpen={() => onOpen(skill.id)} />
      ))}
    </div>
  );
}
