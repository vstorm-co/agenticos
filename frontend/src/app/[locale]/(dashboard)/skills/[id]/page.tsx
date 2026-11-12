"use client";

import { use } from "react";
import { SkillDetails } from "@/components/skills/skill-details";

export default function SkillPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return <SkillDetails id={id} />;
}
