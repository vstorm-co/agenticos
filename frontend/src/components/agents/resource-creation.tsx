"use client";

import { useState, type Dispatch, type SetStateAction } from "react";
import { CreateSkillDialog } from "@/components/skills/create-skill-dialog";
import { CreateContextDialog } from "@/components/context/create-context-dialog";
import { withSkills, withContextFiles } from "@/lib/agent-spec";
import type { AgentSpec } from "@/types/agents";
import type { SkillChoice } from "./skill-gallery";
import type { ContextChoice } from "./context-gallery";

/** Keep newly written choices visible even when the catalog only fetched its first page. */
export function mergeResourceChoices<T extends { id: string }>(catalog: T[], created: T[]): T[] {
  const known = new Set(catalog.map((item) => item.id));
  return [...catalog, ...created.filter((item) => !known.has(item.id))];
}

export function useResourceCreation({
  mayCreateSkill,
  mayCreateContext,
  setSpec,
}: {
  mayCreateSkill: boolean;
  mayCreateContext: boolean;
  setSpec: Dispatch<SetStateAction<AgentSpec | null>>;
}) {
  const [creating, setCreating] = useState<"skill" | "context" | null>(null);
  const [skills, setSkills] = useState<SkillChoice[]>([]);
  const [context, setContext] = useState<ContextChoice[]>([]);
  const close = () => setCreating(null);
  return {
    skills,
    context,
    createSkill: mayCreateSkill ? () => setCreating("skill") : undefined,
    createContext: mayCreateContext ? () => setCreating("context") : undefined,
    dialogs: (
      <>
        {creating === "skill" && mayCreateSkill && (
          <CreateSkillDialog
            open
            onOpenChange={close}
            onCreated={(skill) => {
              setSkills((items) =>
                mergeResourceChoices(items, [
                  { id: skill.id, name: skill.name, description: skill.description },
                ]),
              );
              setSpec((current) =>
                current
                  ? {
                      ...current,
                      ...withSkills(current, [...new Set([...current.skill_ids, skill.id])]),
                    }
                  : current,
              );
              close();
            }}
          />
        )}
        {creating === "context" && mayCreateContext && (
          <CreateContextDialog
            open
            onOpenChange={close}
            onCreated={(file) => {
              setContext((items) =>
                mergeResourceChoices(items, [
                  {
                    id: file.id,
                    name: file.name,
                    description: file.description,
                    mode: file.mode,
                    enabled: file.enabled,
                  },
                ]),
              );
              setSpec((current) =>
                current
                  ? {
                      ...current,
                      ...withContextFiles(current, [...new Set([...current.context_ids, file.id])]),
                    }
                  : current,
              );
              close();
            }}
          />
        )}
      </>
    ),
  };
}
