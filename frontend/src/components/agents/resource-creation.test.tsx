import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import type { AgentSpec } from "@/types/agents";
import type { Skill, ContextFile } from "@/types/providers";
import { mergeResourceChoices, useResourceCreation } from "./resource-creation";

vi.mock("@/components/skills/create-skill-dialog", () => ({
  CreateSkillDialog: ({
    onCreated,
    onOpenChange,
  }: {
    onCreated: (skill: Skill) => void;
    onOpenChange: (open: boolean) => void;
  }) => (
    <>
      <button
        onClick={() =>
          onCreated({
            id: "new-skill",
            name: "New",
            description: "Procedure",
            content: "",
            category: null,
            version: 1,
            visibility: "org",
            owner_user_id: null,
          })
        }
      >
        Save skill
      </button>
      <button onClick={() => onOpenChange(false)}>Cancel</button>
    </>
  ),
}));
vi.mock("@/components/context/create-context-dialog", () => ({
  CreateContextDialog: ({ onCreated }: { onCreated: (file: ContextFile) => void }) => (
    <button
      onClick={() =>
        onCreated({
          id: "new-context",
          name: "Brand",
          description: "Voice",
          content: "",
          mode: "inject",
          enabled: true,
          format: "md",
          visibility: "org",
          owner_user_id: null,
        })
      }
    >
      Save context
    </button>
  ),
}));

const initial: AgentSpec = {
  spec_version: 5,
  name: "Support",
  description: null,
  instructions: "Keep this",
  model_profile_id: null,
  model_settings: {},
  capabilities: [],
  collection_ids: [],
  skill_ids: [],
  context_ids: [],
  mcp_servers: [],
  budget: null,
};
function Builder({ allowed = true }: { allowed?: boolean }) {
  const [spec, setSpec] = useState<AgentSpec | null>(initial);
  const creation = useResourceCreation({
    mayCreateSkill: allowed,
    mayCreateContext: allowed,
    setSpec,
  });
  return (
    <>
      {creation.createSkill && <button onClick={creation.createSkill}>Write skill</button>}
      {creation.createContext && <button onClick={creation.createContext}>Write context</button>}
      <output aria-label="Spec">{JSON.stringify(spec)}</output>
      <output aria-label="Created choices">
        {JSON.stringify([creation.skills, creation.context])}
      </output>
      {creation.dialogs}
    </>
  );
}

it.each([
  ["skill", "skills", "skill_ids", "new-skill"],
  ["context", "context", "context_ids", "new-context"],
])(
  "attaches a created %s and enables its capability on the current draft",
  async (kind, capability, field, id) => {
    render(<Builder />);
    await userEvent.click(screen.getByRole("button", { name: `Write ${kind}` }));
    await userEvent.click(screen.getByRole("button", { name: `Save ${kind}` }));
    expect(screen.getByLabelText("Spec")).toHaveTextContent(`"${field}":["${id}"]`);
    expect(screen.getByLabelText("Spec")).toHaveTextContent(`"id":"${capability}"`);
    expect(screen.getByLabelText("Spec")).toHaveTextContent('"instructions":"Keep this"');
    expect(screen.getByLabelText("Created choices")).toHaveTextContent(id);
    expect(screen.queryByRole("button", { name: `Save ${kind}` })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: `Write ${kind}` }));
    await userEvent.click(screen.getByRole("button", { name: `Save ${kind}` }));
    expect(screen.getByLabelText("Spec")).toHaveTextContent(`"${field}":["${id}"]`);
  },
);

it("leaves the draft alone when creation is cancelled", async () => {
  render(<Builder />);
  await userEvent.click(screen.getByRole("button", { name: "Write skill" }));
  await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(screen.getByLabelText("Spec")).toHaveTextContent(JSON.stringify(initial));
});

it("does not offer writable dialogs without permission", () => {
  render(<Builder allowed={false} />);
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
});

it("keeps a new choice outside the fetched page and prefers refreshed server metadata", () => {
  expect(mergeResourceChoices([{ id: "old", name: "Old" }], [{ id: "new", name: "New" }])).toEqual([
    { id: "old", name: "Old" },
    { id: "new", name: "New" },
  ]);
  expect(
    mergeResourceChoices([{ id: "new", name: "Updated" }], [{ id: "new", name: "New" }]),
  ).toEqual([{ id: "new", name: "Updated" }]);
});
