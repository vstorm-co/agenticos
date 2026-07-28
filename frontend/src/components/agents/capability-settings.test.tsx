import { describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import {
  CapabilitySettings,
  resolveToolApproval,
  secretProblem,
  toolNameError,
} from "./capability-settings";
import type { CapabilityBindingSpec, CapabilityCatalogEntry } from "@/types/agents";
import type { Secret, SecretRequirement } from "@/types/secrets";

const KNOWLEDGE: CapabilityCatalogEntry = {
  id: "knowledge",
  name: "Knowledge search",
  category: "knowledge",
  description: "Search the collections this agent is connected to.",
  side_effecting: false,
  scopes: ["knowledge:read"],
  tools: [
    {
      id: "search_documents",
      name: "search_documents",
      description: "Search the organization's documents for relevant passages.",
    },
  ],
  config_schema: {
    type: "object",
    properties: {
      default_top_k: { type: "integer", default: 5, minimum: 1, maximum: 50 },
    },
  },
  contracts: [],
  requires_secret: null,
};

const CLOCK: CapabilityCatalogEntry = {
  id: "clock",
  name: "Date and time",
  category: "utility",
  description: "Read the current date and time.",
  side_effecting: false,
  scopes: [],
  tools: [],
  config_schema: null,
  contracts: [],
  requires_secret: null,
};

const SEND_EMAIL: CapabilityCatalogEntry = {
  id: "send_email",
  name: "Send email",
  category: "action",
  description: "Send a message on the organization's behalf.",
  side_effecting: true,
  scopes: [],
  tools: [],
  config_schema: null,
  contracts: [],
  requires_secret: null,
};

/**
 * The case per-tool approval exists for: one capability, one tool that reads and
 * one that acts. Gating the whole thing would put a draft in the approval queue;
 * gating nothing would let it send.
 */
const EMAIL: CapabilityCatalogEntry = {
  id: "email",
  name: "Email",
  category: "action",
  description: "Read, draft and send mail.",
  side_effecting: true,
  scopes: [],
  tools: [
    { id: "draft_email", name: "draft_email", description: "Write a message without sending it." },
    { id: "send_email", name: "send_email", description: "Send a message to its recipients." },
  ],
  config_schema: null,
  contracts: [],
  requires_secret: null,
};

const binding = (
  id: string,
  overrides: Partial<CapabilityBindingSpec> = {},
): CapabilityBindingSpec => ({
  id,
  config: {},
  approval: "default",
  tool_approval: {},
  tool_overrides: {},
  secret_id: null,
  enabled: true,
  ...overrides,
});

/** A tool's row, found by the stable id it is labelled with - a rename cannot move it. */
const toolRow = (id: string) => screen.getByRole("listitem", { name: id });

/** One control inside that row. Every row names its fields the same way. */
const toolField = (id: string, label: "Name" | "Description" | "Approval") =>
  within(toolRow(id)).getByLabelText(label);

describe("CapabilitySettings", () => {
  it("shows every bound capability, configurable or not", () => {
    // Each one has at least an approval mode to set. Hiding the plain ones
    // used to hide the approval control with them - and since no builtin is
    // side-effecting, that meant hiding it always.
    render(
      <CapabilitySettings
        catalog={[KNOWLEDGE, CLOCK]}
        selected={[binding("knowledge"), binding("clock")]}
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByText("Knowledge search")).toBeInTheDocument();
    expect(screen.getByText("Date and time")).toBeInTheDocument();
  });

  it("shows a side-effecting capability even without settings", () => {
    // Its approval choice is the setting.
    render(
      <CapabilitySettings
        catalog={[SEND_EMAIL]}
        selected={[binding("send_email")]}
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByText("Send email")).toBeInTheDocument();
    expect(screen.getByText(/acts on the outside world/)).toBeInTheDocument();
  });

  it("skips a capability that was switched off", () => {
    const { container } = render(
      <CapabilitySettings
        catalog={[KNOWLEDGE]}
        selected={[binding("knowledge", { enabled: false })]}
        onChange={vi.fn()}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("ignores a binding whose capability is no longer in the catalog", () => {
    // A spec published before a capability was removed must still open.
    const { container } = render(
      <CapabilitySettings catalog={[]} selected={[binding("retired")]} onChange={vi.fn()} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("reports a config change against the right binding", async () => {
    const onChange = vi.fn();
    render(
      <CapabilitySettings
        catalog={[KNOWLEDGE]}
        selected={[binding("knowledge")]}
        onChange={onChange}
      />,
    );
    await userEvent.type(screen.getByLabelText(/Default top k/), "9");
    expect(onChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ id: "knowledge", config: { default_top_k: 9 } }),
    );
  });

  it("offers an approval choice for a read-only capability too", async () => {
    // The backend honours `required` on any capability, so "this only reads,
    // but somebody here approves it anyway" is a decision an operator makes.
    // There was no way to express it while the control was hidden.
    const onChange = vi.fn();
    render(
      <CapabilitySettings
        catalog={[KNOWLEDGE, SEND_EMAIL]}
        selected={[binding("knowledge"), binding("send_email")]}
        onChange={onChange}
      />,
    );

    expect(screen.getAllByText("Human approval")).toHaveLength(2);
  });

  it("says what default resolves to for this particular capability", () => {
    // The same "Follow the capability" means opposite things either side of
    // `side_effecting`, so the label alone does not answer the question.
    render(
      <CapabilitySettings
        catalog={[KNOWLEDGE, SEND_EMAIL]}
        selected={[binding("knowledge"), binding("send_email")]}
        onChange={vi.fn()}
      />,
    );

    expect(screen.getByText(/Runs without approval/)).toBeInTheDocument();
    expect(screen.getByText(/Held for approval/)).toBeInTheDocument();
  });

  it("shows the mode the spec actually stored", () => {
    // The direction that matters here: opening a published agent must show what
    // it will do, not the default. Driving the select the other way needs a
    // real browser - Radix listens for pointer events jsdom does not dispatch -
    // so that half is asserted in the E2E suite, not faked here.
    render(
      <CapabilitySettings
        catalog={[KNOWLEDGE]}
        selected={[binding("knowledge", { approval: "required" })]}
        onChange={vi.fn()}
      />,
    );

    expect(screen.getByLabelText("Human approval")).toHaveTextContent("Always ask");
  });

  it("explains what the selected approval mode means", () => {
    render(
      <CapabilitySettings
        catalog={[SEND_EMAIL]}
        selected={[binding("send_email", { approval: "never" })]}
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByText(/acts unattended/)).toBeInTheDocument();
  });

  it("shows the registry id, because that is what a stored spec contains", () => {
    render(
      <CapabilitySettings
        catalog={[KNOWLEDGE]}
        selected={[binding("knowledge")]}
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByText("knowledge")).toBeInTheDocument();
  });

  it("does not accept edits when the viewer cannot edit", async () => {
    const onChange = vi.fn();
    render(
      <CapabilitySettings
        catalog={[KNOWLEDGE]}
        selected={[binding("knowledge")]}
        onChange={onChange}
        disabled
      />,
    );
    await userEvent.type(screen.getByLabelText(/Default top k/), "9");
    expect(onChange).not.toHaveBeenCalled();
  });

  it("wires every label to the control it names", () => {
    // A label with no htmlFor reads as decoration to a screen reader and leaves
    // the control it describes unnamed. This regressed once already, and every
    // tool of every capability now adds three more.
    const { container } = render(
      <CapabilitySettings
        catalog={[KNOWLEDGE, EMAIL]}
        selected={[binding("knowledge"), binding("email")]}
        onChange={vi.fn()}
      />,
    );
    const labels = Array.from(container.querySelectorAll<HTMLLabelElement>("label"));

    expect(labels.length).toBeGreaterThan(0);
    for (const label of labels) {
      expect(label.htmlFor, `"${label.textContent}" names no control`).not.toBe("");
      expect(document.getElementById(label.htmlFor)).not.toBeNull();
    }
  });
});

describe("CapabilitySettings tools", () => {
  it("lists every tool a capability exposes, with the name and description the model gets", () => {
    // Both are prompt: the description is what the model reads before deciding
    // to call, and "send_email" and "draft_email" are one letter apart in a
    // list. Editing them is the point of the row.
    render(
      <CapabilitySettings catalog={[EMAIL]} selected={[binding("email")]} onChange={vi.fn()} />,
    );

    expect(toolField("draft_email", "Name")).toHaveValue("draft_email");
    expect(toolField("draft_email", "Description")).toHaveValue(
      "Write a message without sending it.",
    );
    expect(toolField("send_email", "Name")).toHaveValue("send_email");
    expect(toolField("send_email", "Description")).toHaveValue("Send a message to its recipients.");
  });

  it("shows no tool list for a capability that is not tools", () => {
    // A clock puts the time in the instructions. An empty "Tools" heading over
    // an empty box would imply something is missing.
    render(
      <CapabilitySettings catalog={[CLOCK]} selected={[binding("clock")]} onChange={vi.fn()} />,
    );
    expect(screen.queryByText("Tools")).not.toBeInTheDocument();
  });

  it("shows the override the spec stored for one tool, and the default for the rest", () => {
    // Same limitation as the capability-level select: jsdom cannot drive Radix,
    // so what is proved here is that a stored decision reaches the control it
    // belongs to - and only that one.
    render(
      <CapabilitySettings
        catalog={[EMAIL]}
        selected={[
          binding("email", { approval: "never", tool_approval: { send_email: "required" } }),
        ]}
        onChange={vi.fn()}
      />,
    );

    expect(toolField("send_email", "Approval")).toHaveTextContent("Always ask");
    expect(toolField("draft_email", "Approval")).toHaveTextContent(/Follow the capability/);
  });

  it("says what following the capability means for this tool, not in general", () => {
    // "Follow the capability" resolves differently for the same tool depending
    // on the capability's own mode, and a reader holding that rule in their head
    // is a reader who eventually gets it wrong.
    const { rerender } = render(
      <CapabilitySettings
        catalog={[EMAIL]}
        selected={[binding("email", { approval: "never" })]}
        onChange={vi.fn()}
      />,
    );
    expect(toolField("send_email", "Approval")).toHaveTextContent(/never ask/);

    rerender(
      <CapabilitySettings
        catalog={[EMAIL]}
        selected={[binding("email", { approval: "required" })]}
        onChange={vi.fn()}
      />,
    );
    expect(toolField("send_email", "Approval")).toHaveTextContent(/always ask/);
  });

  it("marks the tool that was changed, so the one exception is visible", () => {
    render(
      <CapabilitySettings
        catalog={[EMAIL]}
        selected={[binding("email", { tool_approval: { send_email: "required" } })]}
        onChange={vi.fn()}
      />,
    );

    const rows = screen.getAllByRole("listitem");
    const overridden = rows.filter((row) => within(row).queryByText("overridden") !== null);

    expect(overridden).toHaveLength(1);
    expect(overridden[0]).toHaveTextContent("send_email");
  });

  it("treats a stored 'default' as no override at all", () => {
    // A hand-written or exported spec may spell out what the absence of a key
    // already says. Badging it as an exception would send someone hunting for a
    // decision nobody made.
    render(
      <CapabilitySettings
        catalog={[EMAIL]}
        selected={[binding("email", { tool_approval: { send_email: "default" } })]}
        onChange={vi.fn()}
      />,
    );
    expect(screen.queryByText("overridden")).not.toBeInTheDocument();
  });

  it("clears every override at once, so the capability setting reaches all of them", async () => {
    // Without this, a capability whose default was changed leaves whichever
    // tools were overridden earlier behind, and finding them means reading
    // every row. A rename counts as one: the count is tools that differ, not
    // fields that do.
    const onChange = vi.fn();
    render(
      <CapabilitySettings
        catalog={[EMAIL]}
        selected={[
          binding("email", {
            tool_approval: { send_email: "required" },
            tool_overrides: { draft_email: { description: "Compose but never send." } },
          }),
        ]}
        onChange={onChange}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: "Clear 2 overrides" }));

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ id: "email", tool_approval: {}, tool_overrides: {} }),
    );
  });

  it("offers nothing to clear when no tool was changed", () => {
    render(
      <CapabilitySettings catalog={[EMAIL]} selected={[binding("email")]} onChange={vi.fn()} />,
    );
    expect(screen.queryByRole("button", { name: /Clear/ })).not.toBeInTheDocument();
  });

  it("does not accept a tool change when the viewer cannot edit", async () => {
    const onChange = vi.fn();
    render(
      <CapabilitySettings
        catalog={[EMAIL]}
        selected={[binding("email", { tool_approval: { send_email: "required" } })]}
        onChange={onChange}
        disabled
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: "Clear 1 override" }));
    expect(onChange).not.toHaveBeenCalled();
  });
});

describe("CapabilitySettings tool renaming", () => {
  it("records a rename against the tool's id, not the name being replaced", async () => {
    // Keying on the name would make the second rename a new tool and orphan the
    // first - and would move the approval gate with it.
    const onChange = vi.fn();
    render(
      <CapabilitySettings catalog={[EMAIL]} selected={[binding("email")]} onChange={onChange} />,
    );

    await userEvent.type(toolField("send_email", "Name"), "2");

    expect(onChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ tool_overrides: { send_email: { name: "send_email2" } } }),
    );
  });

  it("records a rewritten description the same way", async () => {
    const onChange = vi.fn();
    render(
      <CapabilitySettings catalog={[EMAIL]} selected={[binding("email")]} onChange={onChange} />,
    );

    await userEvent.type(toolField("draft_email", "Description"), "!");

    expect(onChange).toHaveBeenLastCalledWith(
      expect.objectContaining({
        tool_overrides: { draft_email: { description: "Write a message without sending it.!" } },
      }),
    );
  });

  it("shows the name and description this agent will really offer", () => {
    // The catalog hands back effective values, so a saved override arrives
    // already applied. What this proves is that an unsaved one, which the
    // catalog has not seen, wins over the value beside it.
    render(
      <CapabilitySettings
        catalog={[EMAIL]}
        selected={[
          binding("email", {
            tool_overrides: {
              send_email: { name: "send_invoice", description: "Send the invoice we drafted." },
            },
          }),
        ]}
        onChange={vi.fn()}
      />,
    );

    expect(toolField("send_email", "Name")).toHaveValue("send_invoice");
    expect(toolField("send_email", "Description")).toHaveValue("Send the invoice we drafted.");
    expect(toolField("draft_email", "Name")).toHaveValue("draft_email");
  });

  it("marks a renamed tool with the badge per-tool approval already uses", () => {
    // One visual language for "this row differs", whichever of the three things
    // on it was changed.
    render(
      <CapabilitySettings
        catalog={[EMAIL]}
        selected={[binding("email", { tool_overrides: { send_email: { name: "send_invoice" } } })]}
        onChange={vi.fn()}
      />,
    );

    expect(within(toolRow("send_email")).getByText("overridden")).toBeInTheDocument();
    expect(within(toolRow("draft_email")).queryByText("overridden")).not.toBeInTheDocument();
  });

  it("leaves a renamed tool gated exactly as it was", () => {
    // The gate is keyed on the id precisely so this holds. A rename that moved
    // it would let a side-effecting call run unattended, and nothing would say
    // so.
    render(
      <CapabilitySettings
        catalog={[EMAIL]}
        selected={[
          binding("email", {
            tool_approval: { send_email: "required" },
            tool_overrides: { send_email: { name: "send_invoice" } },
          }),
        ]}
        onChange={vi.fn()}
      />,
    );

    expect(toolField("send_email", "Name")).toHaveValue("send_invoice");
    expect(toolField("send_email", "Approval")).toHaveTextContent("Always ask");
  });

  it("puts a renamed tool back without asking what it used to be called", async () => {
    // The whole reason a reset exists: somebody who renamed a tool an hour ago
    // cannot type the original back, because the original is exactly what they
    // no longer have.
    const onChange = vi.fn();
    const { rerender } = render(
      <CapabilitySettings
        catalog={[EMAIL]}
        selected={[binding("email", { tool_overrides: { send_email: { name: "send_invoice" } } })]}
        onChange={onChange}
      />,
    );

    await userEvent.click(
      within(toolRow("send_email")).getByRole("button", { name: "Reset name" }),
    );

    const reverted = onChange.mock.lastCall?.[0] as CapabilityBindingSpec;
    expect(reverted.tool_overrides).toEqual({});

    rerender(<CapabilitySettings catalog={[EMAIL]} selected={[reverted]} onChange={onChange} />);
    expect(toolField("send_email", "Name")).toHaveValue("send_email");
  });

  it("resets one field without taking the other with it", async () => {
    // Rewriting the description is the common edit and the one worth keeping;
    // a reset that threw it away with the name would teach people not to touch
    // either.
    const onChange = vi.fn();
    render(
      <CapabilitySettings
        catalog={[EMAIL]}
        selected={[
          binding("email", {
            tool_overrides: {
              send_email: { name: "send_invoice", description: "Send the invoice we drafted." },
            },
          }),
        ]}
        onChange={onChange}
      />,
    );

    await userEvent.click(
      within(toolRow("send_email")).getByRole("button", { name: "Reset name" }),
    );

    expect(onChange).toHaveBeenLastCalledWith(
      expect.objectContaining({
        tool_overrides: { send_email: { description: "Send the invoice we drafted." } },
      }),
    );
  });

  it("offers a reset only for the field that was changed", () => {
    // The button is the field's override marker as much as its remedy - one
    // beside every field would say nothing.
    render(
      <CapabilitySettings
        catalog={[EMAIL]}
        selected={[binding("email", { tool_overrides: { send_email: { name: "send_invoice" } } })]}
        onChange={vi.fn()}
      />,
    );

    const row = within(toolRow("send_email"));
    expect(row.getByRole("button", { name: "Reset name" })).toBeInTheDocument();
    expect(row.queryByRole("button", { name: "Reset description" })).not.toBeInTheDocument();
    expect(
      within(toolRow("draft_email")).queryByRole("button", { name: /Reset/ }),
    ).not.toBeInTheDocument();
  });

  it("says why a name the model could not call will not do", async () => {
    // The backend refuses it too. Being told at the field beats being told by a
    // failed save, and "invalid" alone leaves the reader guessing which of the
    // rules they broke.
    const onChange = vi.fn();
    render(
      <CapabilitySettings
        catalog={[EMAIL]}
        selected={[binding("email", { tool_overrides: { send_email: { name: "send invoice!" } } })]}
        onChange={onChange}
      />,
    );

    expect(toolField("send_email", "Name")).toBeInvalid();
    expect(within(toolRow("send_email")).getByText(/underscores only/)).toBeInTheDocument();

    // Emptying the field is not a way back to the default - that is the reset
    // button - so it is refused rather than silently treated as one.
    await userEvent.clear(toolField("send_email", "Name"));
    expect(onChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ tool_overrides: { send_email: { name: "" } } }),
    );
  });

  it("says a blank name is not a name", () => {
    render(
      <CapabilitySettings
        catalog={[EMAIL]}
        selected={[binding("email", { tool_overrides: { send_email: { name: "" } } })]}
        onChange={vi.fn()}
      />,
    );
    expect(within(toolRow("send_email")).getByText(/cannot be blank/)).toBeInTheDocument();
  });

  it("does not accept a rename or a reset when the viewer cannot edit", async () => {
    const onChange = vi.fn();
    render(
      <CapabilitySettings
        catalog={[EMAIL]}
        selected={[binding("email", { tool_overrides: { send_email: { name: "send_invoice" } } })]}
        onChange={onChange}
        disabled
      />,
    );

    await userEvent.type(toolField("send_email", "Name"), "x");
    await userEvent.click(
      within(toolRow("send_email")).getByRole("button", { name: "Reset name" }),
    );
    expect(onChange).not.toHaveBeenCalled();
  });
});

describe("toolNameError", () => {
  it("accepts what a model can emit as a tool call", () => {
    expect(toolNameError("search_documents")).toBeNull();
    expect(toolNameError("search_refund_policy_v2")).toBeNull();
    expect(toolNameError("_internal")).toBeNull();
  });

  it("refuses a name with a space, because the call would name nothing", () => {
    expect(toolNameError("search documents")).toMatch(/underscores only/);
  });

  it("refuses punctuation an identifier cannot carry", () => {
    // Hyphens are the near miss: they read like a name and are not one.
    expect(toolNameError("search-documents")).toMatch(/underscores only/);
    expect(toolNameError("search.documents")).toMatch(/underscores only/);
    expect(toolNameError("search()")).toMatch(/underscores only/);
  });

  it("refuses a leading digit", () => {
    expect(toolNameError("2nd_search")).toMatch(/underscores only/);
  });

  it("refuses nothing at all", () => {
    expect(toolNameError("")).toMatch(/cannot be blank/);
  });
});

/**
 * A secret left on a capability that consumes none.
 *
 * No hook is involved - a capability that declares no requirement gets no
 * picker, so nothing here reads the vault - which is why these live beside the
 * prop-driven tests rather than in the integration file.
 */
describe("CapabilitySettings stale secret reference", () => {
  it("says a secret on a capability that uses none is refused, and offers the way out", async () => {
    // The fourth thing publishing refuses about secrets, and the only one nobody
    // would notice: the binding reads as configured and the value is never read.
    // It arrives when a capability drops its requirement while an agent still
    // names a secret for it, and no picker is rendered to take it back.
    const onChange = vi.fn();
    render(
      <CapabilitySettings
        catalog={[CLOCK]}
        selected={[binding("clock", { secret_id: "sec-1" })]}
        onChange={onChange}
      />,
    );

    expect(screen.getByText(/stored and never read/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Clear secret" }));
    expect(onChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ id: "clock", secret_id: null }),
    );
  });

  it("says nothing about secrets for a capability that neither needs nor names one", () => {
    render(
      <CapabilitySettings catalog={[CLOCK]} selected={[binding("clock")]} onChange={vi.fn()} />,
    );
    expect(screen.queryByText(/stored and never read/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Clear secret" })).not.toBeInTheDocument();
  });

  it("does not clear it when the viewer cannot edit", async () => {
    const onChange = vi.fn();
    render(
      <CapabilitySettings
        catalog={[CLOCK]}
        selected={[binding("clock", { secret_id: "sec-1" })]}
        onChange={onChange}
        disabled
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: "Clear secret" }));
    expect(onChange).not.toHaveBeenCalled();
  });
});

describe("secretProblem", () => {
  const API_KEY: SecretRequirement = {
    kind: "api_key",
    description: "The weather API key.",
    required_when: null,
  };
  const stored: Secret = {
    id: "sec-1",
    name: "Weather API key",
    description: null,
    kind: "api_key",
    hint: "P7KD",
  };

  it("accepts a secret of the kind the capability declared", () => {
    expect(secretProblem(API_KEY, "sec-1", [stored])).toBeNull();
  });

  it("says that nothing selected is what blocks publishing", () => {
    // The refusal an author reaches by doing nothing, which is why it is said at
    // the control rather than left to the publish attempt.
    expect(secretProblem(API_KEY, null, [stored])).toMatch(/cannot be published/);
  });

  it("says a reference the organization cannot satisfy is refused", () => {
    // A deleted secret, or a spec imported from another organization - the
    // binding keeps an id that resolves to nothing.
    expect(secretProblem(API_KEY, "sec-gone", [stored])).toMatch(/not in this organization/);
  });

  it("names the mismatch when the secret is the wrong shape", () => {
    // The one refusal a picker filtered by kind should never produce, and the
    // one an imported or hand-written spec produces anyway.
    const aws: Secret = {
      id: "sec-2",
      name: "Ingest role",
      description: null,
      kind: "aws_credentials",
      hint: "AKIA",
    };
    expect(secretProblem(API_KEY, "sec-2", [aws])).toMatch(
      /"Ingest role" is of kind aws_credentials; this capability needs api_key/,
    );
  });
});

describe("resolveToolApproval", () => {
  it("prefers the tool's own answer over the capability's", () => {
    expect(
      resolveToolApproval(
        binding("email", { approval: "never", tool_approval: { send_email: "required" } }),
        "send_email",
        true,
      ),
    ).toBe("required");
  });

  it("falls back to the capability when the tool has no answer", () => {
    expect(
      resolveToolApproval(binding("email", { approval: "required" }), "draft_email", false),
    ).toBe("required");
  });

  it("falls back to side_effecting when neither has one", () => {
    // The last rule, and the only one nobody typed: a capability that changes
    // something outside the agent is gated until somebody says otherwise.
    expect(resolveToolApproval(binding("email"), "send_email", true)).toBe("required");
    expect(resolveToolApproval(binding("knowledge"), "search_documents", false)).toBe("never");
  });
});
