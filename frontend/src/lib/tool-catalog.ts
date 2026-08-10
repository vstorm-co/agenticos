/**
 * Every tool the backend registers, and what this side does with it.
 *
 * One table, keyed on the **stable tool id** a capability declares in
 * `backend/app/agents/capabilities/<name>/__init__.py`. That key is the whole point: the
 * knowledge about a tool used to sit in three files independently - the icon in
 * `tool-steps.ts`, the caption in `agent-step-captions.ts`, the renderer in
 * `tool-call-card.tsx` - so a rename landed in one of them and the other two went on
 * matching a name nothing emits. `web_search` and `create_chart` spent five weeks
 * rendering as pretty-printed JSON next to the renderers written for them, with green
 * tests, because the tests asserted on the old names too (#144).
 *
 * So this table holds the registry's tool ids and nothing else, and
 * `backend/tests/test_capability_registry.py::TestFrontendToolCatalog` fails in both
 * directions until it does. A row is a decision, not paperwork - which icon the step
 * carries, what it says while it runs, and what opens underneath it when it is done.
 *
 * A name arriving from anywhere *other* than the registry has no row and needs none:
 * MCP tools come prefixed with their connection's name, and a binding may rename a
 * tool it exposes. Those fall back to a humanized name and the generic renderer,
 * which is the honest answer for a tool this side has never heard of.
 *
 * Dependency-free on purpose - it is the vocabulary, not the presentation.
 */

/** What kind of thing a step is about, which is what picks its icon. */
export type StepKind =
  | "write"
  | "edit"
  | "read"
  | "list"
  | "search"
  | "shell"
  | "chart"
  | "knowledge"
  | "web"
  | "skill"
  | "code"
  | "delegate"
  | "mcp"
  | "tool";

/**
 * Which renderer opens under a finished call.
 *
 * A name rather than the component itself, so this table stays importable from a
 * test, a hook and a server component - the components live in
 * `components/chat/tool-results/` and one of them pulls in Recharts.
 *
 * `"none"` is a call with nothing worth opening: the step says the agent looked, and
 * what it got back is a prompt fragment rather than something a person reads.
 */
export type ToolRenderer =
  "chart" | "web-search" | "rag" | "run-python" | "load-skill" | "workspace" | "generic" | "none";

/** The tense pair for a step that names its own subject: *Writing test1.md*. */
export interface ToolVerbs {
  /** While it runs. */
  now: string;
  /** Once it has finished. */
  done: string;
}

export interface ToolEntry {
  kind: StepKind;
  render: ToolRenderer;
  /** Present tense, while the call runs. Defaults to "Running <Name>". */
  caption?: string;
  /** What the finished step is called. Defaults to the humanized id. */
  displayName?: string;
  /** Set instead of `caption` when the label is a verb plus the call's subject. */
  verbs?: ToolVerbs;
  /**
   * Open this step when it finishes in front of somebody.
   *
   * The calls whose whole value is the thing they produced - a chart, code that ran,
   * a file that was written. Everything else stays a line somebody can open.
   */
  opensWhenDone?: boolean;
  /**
   * Open this step whenever it is on screen, not only as it finishes.
   *
   * `opensWhenDone` needs a status *transition* to fire, and a step whose result
   * arrived with it never has one - it mounts already completed. Only the last
   * step of a turn is opened on mount (`startOpen` in `message-item.tsx`), so a
   * turn that drew three charts showed two collapsed headers and one picture.
   *
   * For a chart that is wrong: the picture *is* the answer, and three of them are
   * three answers rather than one with two footnotes. This is deliberately not
   * set on `write_file`, `edit_file` or `run_python` - those confirm that
   * something happened, and opening every one of them on sight is what made a
   * replayed conversation a wall of diffs.
   */
  opensOnSight?: boolean;
}

/**
 * The table. Grouped by the capability that registers each tool.
 *
 * Ordered as `all_capabilities()` returns them, so a diff here reads against a diff
 * there.
 */
export const TOOL_CATALOG: Record<string, ToolEntry> = {
  // channel_tools - only ever called on a Slack, Telegram or Mattermost run, so these
  // steps are read back in the run timeline rather than watched live in the dashboard.
  get_channel_info: {
    kind: "read",
    render: "generic",
    caption: "Looking at the channel",
    displayName: "Channel Info",
  },
  list_channel_members: {
    kind: "list",
    render: "generic",
    caption: "Looking at who is in the channel",
    displayName: "Channel Members",
  },
  search_channels: {
    kind: "search",
    render: "generic",
    caption: "Looking for a channel",
    displayName: "Channel Search",
  },
  read_channel_history: {
    kind: "read",
    render: "generic",
    caption: "Reading the channel",
    displayName: "Channel History",
  },

  // charts
  create_chart: {
    kind: "chart",
    render: "chart",
    caption: "Creating a chart",
    displayName: "Chart",
    opensWhenDone: true,
    opensOnSight: true,
  },

  // sandbox - the workspace toolset, whose steps name the file they are about
  ls: { kind: "list", render: "workspace", verbs: { now: "Listing", done: "Listed" } },
  read_file: { kind: "read", render: "workspace", verbs: { now: "Reading", done: "Read" } },
  glob: { kind: "search", render: "workspace", verbs: { now: "Looking for", done: "Looked for" } },
  grep: {
    kind: "search",
    render: "workspace",
    verbs: { now: "Searching for", done: "Searched for" },
  },
  write_file: {
    kind: "write",
    render: "workspace",
    verbs: { now: "Writing", done: "Wrote" },
    opensWhenDone: true,
  },
  edit_file: {
    kind: "edit",
    render: "workspace",
    verbs: { now: "Editing", done: "Edited" },
    opensWhenDone: true,
  },
  execute: { kind: "shell", render: "workspace", verbs: { now: "Running", done: "Ran" } },

  // code_execution
  run_python: {
    kind: "code",
    render: "run-python",
    caption: "Running calculations",
    displayName: "Run Python",
    opensWhenDone: true,
  },

  // knowledge
  search_documents: {
    kind: "knowledge",
    render: "rag",
    caption: "Searching the documents",
    displayName: "Knowledge Base Search",
  },

  // skills
  list_skills: {
    kind: "skill",
    render: "none",
    caption: "Looking through the skills",
    displayName: "Available Skills",
  },
  load_skill: {
    kind: "skill",
    render: "load-skill",
    caption: "Loading a skill",
    displayName: "Load Skill",
  },
  read_skill_resource: {
    kind: "skill",
    render: "generic",
    caption: "Reading a skill's files",
    displayName: "Skill Resource",
  },

  // subagents - the parent's half of a delegation. The delegate's own run is a panel
  // of its own, built from `subagent_*` frames rather than from these calls.
  task: { kind: "delegate", render: "generic", caption: "Handing work to a delegate" },
  check_task: { kind: "delegate", render: "generic", caption: "Checking on a delegate" },
  wait_tasks: { kind: "delegate", render: "generic", caption: "Waiting for the delegates" },
  list_active_tasks: {
    kind: "delegate",
    render: "generic",
    caption: "Looking at what is still running",
    displayName: "Active Tasks",
  },
  answer_subagent: {
    kind: "delegate",
    render: "generic",
    caption: "Answering a delegate",
    displayName: "Answer Delegate",
  },
  send_message_to_subagent: {
    kind: "delegate",
    render: "generic",
    caption: "Steering a delegate",
    displayName: "Message Delegate",
  },
  soft_cancel_task: {
    kind: "delegate",
    render: "generic",
    caption: "Asking a delegate to stop",
    displayName: "Stop Task",
  },
  hard_cancel_task: {
    kind: "delegate",
    render: "generic",
    caption: "Cancelling a delegate",
    displayName: "Cancel Task",
  },
  create_agent: {
    kind: "delegate",
    render: "generic",
    caption: "Creating a specialist",
    displayName: "Create Specialist",
  },
  delegate: { kind: "delegate", render: "generic", caption: "Delegating" },

  // web_research
  web_search: {
    kind: "web",
    render: "web-search",
    caption: "Searching the web",
    displayName: "Web Search",
  },
};

/** What this side knows about `name`, or null for a tool it has never heard of. */
export function toolEntry(name: string): ToolEntry | null {
  return TOOL_CATALOG[name] ?? null;
}

/**
 * The tools that come from `pydantic-ai-backends`, which read and write real files.
 *
 * Derived rather than listed: `render: "workspace"` is the same decision, and a second
 * list is a second thing to forget.
 */
export function isWorkspaceTool(name: string): boolean {
  return TOOL_CATALOG[name]?.render === "workspace";
}
