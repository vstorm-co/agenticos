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
  | "image"
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
  | "chart"
  | "generated-image"
  | "web-search"
  | "rag"
  | "run-python"
  | "load-skill"
  | "workspace"
  | "generic"
  | "none";

/**
 * The tense pair for a step that names its own subject: *Writing test1.md*.
 *
 * Two `chat.tools` keys rather than two words, because a verb the sentence around it
 * has to agree with cannot be a parameter - `{verb} {subject}` reads as translated and is the
 * defect `messages/catalog.test.ts` refuses under the name `{noun}` (#362). Each
 * message writes its own whole sentence and selects on `named`, which says whether the
 * call gave a subject at all: `{named, select, no {Writing…} other {Writing {subject}}}`.
 */
export interface ToolVerbs {
  /** While it runs. */
  now: string;
  /** Once it has finished. */
  done: string;
}

export interface ToolEntry {
  kind: StepKind;
  render: ToolRenderer;
  /**
   * Key under `chat.tools` for the present tense, while the call runs. Defaults to
   * `runningNamed`.
   *
   * A key rather than a sentence: this table is a module constant and cannot reach a
   * translator, so the copy is resolved where it is rendered (#446).
   */
  captionKey?: string;
  /**
   * Key under `chat.tools` for what the finished step is called. Defaults to the
   * humanized id.
   */
  displayNameKey?: string;
  /** Set instead of `captionKey` when the label is a verb plus the call's subject. */
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
  // browser_use - one autonomous browsing step; what comes back is a text result, so
  // the generic renderer, not a browser view.
  browse_web: {
    kind: "web",
    render: "generic",
    captionKey: "browsingWeb",
    displayNameKey: "browseWeb",
  },

  // channel_tools - only ever called on a Slack, Telegram or Mattermost run, so these
  // steps are read back in the run timeline rather than watched live in the dashboard.
  get_channel_info: {
    kind: "read",
    render: "generic",
    captionKey: "lookingAtChannel",
    displayNameKey: "channelInfo",
  },
  list_channel_members: {
    kind: "list",
    render: "generic",
    captionKey: "lookingAtChannelMembers",
    displayNameKey: "channelMembers",
  },
  search_channels: {
    kind: "search",
    render: "generic",
    captionKey: "lookingForChannel",
    displayNameKey: "channelSearch",
  },
  read_channel_history: {
    kind: "read",
    render: "generic",
    captionKey: "readingChannel",
    displayNameKey: "channelHistory",
  },

  // charts
  create_chart: {
    kind: "chart",
    render: "chart",
    captionKey: "creatingChart",
    displayNameKey: "chart",
    opensWhenDone: true,
    opensOnSight: true,
  },

  // image_generation - the picture is the answer, so it opens wherever it lands.
  generate_image: {
    kind: "image",
    render: "generated-image",
    captionKey: "generatingImage",
    displayNameKey: "generateImage",
    opensWhenDone: true,
    opensOnSight: true,
  },

  // sandbox - the workspace toolset, whose steps name the file they are about
  ls: { kind: "list", render: "workspace", verbs: { now: "listing", done: "listed" } },
  read_file: { kind: "read", render: "workspace", verbs: { now: "reading", done: "read" } },
  glob: { kind: "search", render: "workspace", verbs: { now: "lookingFor", done: "lookedFor" } },
  grep: {
    kind: "search",
    render: "workspace",
    verbs: { now: "searchingFor", done: "searchedFor" },
  },
  write_file: {
    kind: "write",
    render: "workspace",
    verbs: { now: "writing", done: "wrote" },
    opensWhenDone: true,
  },
  edit_file: {
    kind: "edit",
    render: "workspace",
    verbs: { now: "editing", done: "edited" },
    opensWhenDone: true,
  },
  execute: { kind: "shell", render: "workspace", verbs: { now: "executing", done: "executed" } },

  // code_execution
  run_python: {
    kind: "code",
    render: "run-python",
    captionKey: "runningCalculations",
    displayNameKey: "runPython",
    opensWhenDone: true,
  },

  // context - the link-mode half of the context capability; injected files never
  // reach the model as a tool call, so there is nothing to render for them here.
  list_context: {
    kind: "list",
    render: "none",
    captionKey: "lookingThroughContext",
    displayNameKey: "availableContext",
  },
  read_context: {
    kind: "read",
    render: "generic",
    captionKey: "readingContext",
    displayNameKey: "contextFile",
  },

  // knowledge
  search_documents: {
    kind: "knowledge",
    render: "rag",
    captionKey: "searchingDocuments",
    displayNameKey: "knowledgeBaseSearch",
  },

  // skills
  list_skills: {
    kind: "skill",
    render: "none",
    captionKey: "lookingThroughSkills",
    displayNameKey: "availableSkills",
  },
  load_skill: {
    kind: "skill",
    render: "load-skill",
    captionKey: "loadingSkill",
    displayNameKey: "loadSkill",
  },
  read_skill_resource: {
    kind: "skill",
    render: "generic",
    captionKey: "readingSkillFiles",
    displayNameKey: "skillResource",
  },

  // subagents - the parent's half of a delegation. The delegate's own run is a panel
  // of its own, built from `subagent_*` frames rather than from these calls.
  task: { kind: "delegate", render: "generic", captionKey: "handingWork" },
  check_task: { kind: "delegate", render: "generic", captionKey: "checkingDelegate" },
  wait_tasks: { kind: "delegate", render: "generic", captionKey: "waitingDelegates" },
  list_active_tasks: {
    kind: "delegate",
    render: "generic",
    captionKey: "lookingAtRunning",
    displayNameKey: "activeTasks",
  },
  answer_subagent: {
    kind: "delegate",
    render: "generic",
    captionKey: "answeringDelegate",
    displayNameKey: "answerDelegate",
  },
  send_message_to_subagent: {
    kind: "delegate",
    render: "generic",
    captionKey: "steeringDelegate",
    displayNameKey: "messageDelegate",
  },
  soft_cancel_task: {
    kind: "delegate",
    render: "generic",
    captionKey: "askingDelegateStop",
    displayNameKey: "stopTask",
  },
  hard_cancel_task: {
    kind: "delegate",
    render: "generic",
    captionKey: "cancellingDelegate",
    displayNameKey: "cancelTask",
  },
  create_agent: {
    kind: "delegate",
    render: "generic",
    captionKey: "creatingSpecialist",
    displayNameKey: "createSpecialist",
  },
  delegate: { kind: "delegate", render: "generic", captionKey: "delegating" },

  // planning - the model's own checklist. The tool result is the rendered plan or a
  // one-line confirmation, so nothing opens underneath these steps.
  write_plan: {
    kind: "write",
    render: "generic",
    captionKey: "writingPlan",
    displayNameKey: "plan",
  },
  read_plan: { kind: "read", render: "generic", captionKey: "readingPlan", displayNameKey: "plan" },
  add_task: {
    kind: "write",
    render: "generic",
    captionKey: "addingStep",
    displayNameKey: "addStep",
  },
  update_task_status: {
    kind: "edit",
    render: "generic",
    captionKey: "updatingStep",
    displayNameKey: "updateStep",
  },
  update_task_statuses: {
    kind: "edit",
    render: "generic",
    captionKey: "updatingSteps",
    displayNameKey: "updateSteps",
  },
  remove_task: {
    kind: "edit",
    render: "generic",
    captionKey: "removingStep",
    displayNameKey: "removeStep",
  },
  add_subtask: {
    kind: "write",
    render: "generic",
    captionKey: "addingSubtask",
    displayNameKey: "addSubtask",
  },
  set_dependency: {
    kind: "edit",
    render: "generic",
    captionKey: "settingDependency",
    displayNameKey: "setDependency",
  },
  get_available_tasks: {
    kind: "list",
    render: "generic",
    captionKey: "checkingAvailableSteps",
    displayNameKey: "availableSteps",
  },

  // web_research
  web_search: {
    kind: "web",
    render: "web-search",
    captionKey: "searchingWeb",
    displayNameKey: "webSearch",
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
