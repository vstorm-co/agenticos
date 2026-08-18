/**
 * Types for the agent registry, mirroring the backend's `AgentSpec`.
 *
 * The spec is the contract: the Builder edits it, the API versions it, and a
 * client can export it as YAML into their own repository. Keeping this file a
 * faithful mirror is what stops the Builder from quietly inventing fields the
 * backend will reject at publish.
 */

import type { SecretRequirement } from "./secrets";
import type { Visibility } from "./sharing";

export type AgentStatus = "draft" | "published" | "archived";
export type ApprovalMode = "default" | "required" | "never";

/**
 * What one tool is called and how it is described *for this agent*.
 *
 * Both are prompt, not labelling: the description is what the model reads
 * before deciding whether to call the tool, and the name steers it just as
 * hard - `search_refund_policy` gets chosen for questions `search_documents`
 * would be passed over for. An absent key means the value the capability
 * declared in code.
 */
export interface ToolOverride {
  name?: string;
  description?: string;
}

export interface CapabilityBindingSpec {
  id: string;
  config: Record<string, unknown>;
  /** The default for every tool this capability exposes. */
  approval: ApprovalMode;
  /**
   * Approval for individual tools, keyed by the tool's stable id.
   *
   * A capability is the right unit to switch on; it is the wrong unit to gate.
   * `filesystem` reads and writes, `email` drafts and sends, and holding the
   * safe half for a human is how an approval queue stops being read at all.
   * An id absent here (or mapped to `default`) follows `approval`.
   */
  tool_approval: Record<string, ApprovalMode>;
  /**
   * Renamed and rewritten tools, keyed by the tool's stable id.
   *
   * The id is what both maps key on precisely so a rename cannot move a gate:
   * a tool the model calls by another name is still the tool somebody held for
   * approval.
   */
  tool_overrides: Record<string, ToolOverride>;
  /**
   * Which of the organization's secrets satisfies this capability's
   * requirement, or null when nothing has been chosen.
   *
   * An id, never a value - a spec is exported as YAML into a client's
   * repository. Publishing refuses an id that is missing, belongs to another
   * organization or holds the wrong kind, refuses the absence of one where the
   * capability declares a requirement, and refuses a reference on a capability
   * that consumes none.
   */
  secret_id: string | null;
  enabled: boolean;
}

/** Where this agent's traces go, when not to the deployment's own project. */
export interface ObservabilitySpec {
  /** An organization secret holding a Logfire write token - an id, never a token. */
  token_secret_id?: string | null;
  /** What the agent is called in Logfire; falls back to the agent's name. */
  service_name?: string | null;
  environment?: string | null;
}

/** The agent's half of the two budget levels; the organization's cap is the other. */
export interface BudgetSpec {
  monthly_usd?: number | null;
}

/**
 * Who one of an agent's alerts reaches.
 *
 * Roles rather than addresses, with `chosen` as the one escape hatch: an
 * audience of user ids goes stale the moment somebody leaves, and a spec is
 * exported to a client's repository - `admins` still means the right people
 * after a reorganisation.
 */
export type AlertAudience = "admins" | "owner" | "initiator" | "chosen";

/**
 * Whether one kind of alert is sent for this agent, and to whom.
 *
 * `user_ids` is read only when `to` includes `chosen`, and the backend refuses
 * the two configurations that silently mail nobody: `chosen` with an empty list,
 * and ids without `chosen`.
 */
export interface AlertSpec {
  enabled: boolean;
  to: AlertAudience[];
  user_ids: string[];
}

/**
 * Which of this agent's alerts are sent, and who hears each one.
 *
 * The organization's own monthly cap is deliberately absent. It stops every
 * agent in the organization, its ceiling is set in the organization's settings,
 * and an agent's author cannot raise it - so its alert goes to the
 * administrators and no spec can redirect it.
 */
export interface NotificationSpec {
  budget: AlertSpec;
  approvals: AlertSpec;
  usage: AlertSpec;
}

/**
 * What this agent asks of its model, as far as an author may say so.
 *
 * A small window onto Pydantic AI's `ModelSettings`: the backend refuses every
 * key not listed here, so a control invented in the Builder fails at save
 * rather than at publish.
 *
 * **An absent key means the setting is not sent at all**, which is not the same
 * as sending the provider's default - reasoning models reject `temperature`
 * outright, so an agent whose author never touched it must produce a request
 * with no such key. `undefined`, never `null`: `JSON.stringify` drops the
 * former, and the backend stores what it is given.
 *
 * Reasoning is not here. It is the `thinking` capability, one card down.
 */
export interface ModelSettingsSpec {
  /** 0–2. How varied the answer is; rejected outright by reasoning models. */
  temperature?: number;
  /** 0–1. Nucleus sampling - set this or `temperature`, not both. */
  top_p?: number;
  max_tokens?: number;
  /** Whether the model may call several tools in one step. */
  parallel_tool_calls?: boolean;
  /** Seconds one model request may take before it is abandoned. */
  timeout?: number;
}

/**
 * When a delegation hands control back.
 *
 * `sync` blocks the parent until the delegate answers, `async` starts it and
 * lets the parent carry on, `auto` leaves the choice to the parent's model.
 */
export type DelegationMode = "sync" | "async" | "auto";

/**
 * One published agent this agent may delegate to, pinned to a version.
 *
 * Two ids rather than one, and the second is the point. A reference naming only
 * the agent would let a delegate's behaviour change under a published parent
 * with nothing recording that anything had changed - so a fix to a delegate
 * reaches its callers when somebody says so, which is the guarantee publishing
 * gives everywhere else here.
 *
 * The cost is paid in the Builder: a parent whose delegate has moved on is
 * stale, and staleness nothing surfaces is a bug frozen in place. `pinStatus` in
 * `lib/agent-spec.ts` is what surfaces it.
 */
export interface SubagentRef {
  agent_id: string;
  agent_version_id: string;
  /** Overrides the capability's `mode` for this delegate alone; null follows it. */
  preferred_mode?: DelegationMode | null;
}

/**
 * A specialist defined inside another agent rather than published.
 *
 * An agent in every way except the one that matters: **it is not versioned.** It
 * has no version row, it cannot be pinned, nothing else can reference it, and
 * editing the parent changes it. That is the whole difference from
 * `SubagentRef`, and it is why the Builder presents the two as different things
 * rather than two tabs of one.
 *
 * A typed subset of `AgentSpec` on purpose, using the same
 * `CapabilityBindingSpec` - so one editor serves both and there is no second
 * notion of "agent" for publish validation to miss. `budget`, `notifications`,
 * `observability`, `mcp_server_ids` and `subagents` are deliberately absent:
 * each only means something for a thing with a version, an owner, or a depth
 * left to spend.
 */
export interface SpecialistSpec {
  /** How the parent's model addresses it. `^[a-zA-Z0-9_-]+$`, at most 64 characters. */
  name: string;
  /** What the parent's model reads when deciding whether to delegate here. */
  description: string;
  instructions: string;
  model_profile_id?: string | null;
  model_settings: ModelSettingsSpec;
  capabilities: CapabilityBindingSpec[];
  collection_ids: string[];
  skill_ids: string[];
  context_ids: string[];
  max_steps?: number | null;
  preferred_mode?: DelegationMode | null;
}

/**
 * The delegation capability's own configuration: policy, and the specialists.
 *
 * Delegate *references* are not here - they live on `AgentSpec.subagents`, for
 * the same reason `collection_ids` does: a reference to another row in this
 * organization is a property of the agent, and it is what publish validation
 * walks. What is left is policy, plus the inline specialists, which are not
 * references at all.
 */
export interface SubagentsConfig {
  inline: SpecialistSpec[];
  mode: DelegationMode;
  /** Whether the model may invent a specialist mid-run. Off by default. */
  allow_dynamic: boolean;
  max_depth: number;
  max_fanout: number;
  max_result_chars: number;
  /** Capability ids the parent is bound to that its delegates inherit. */
  share_with_delegates: string[];
}

export interface AgentSpec {
  /**
   * Stamped by the server, never authored here.
   *
   * Present on everything the API returns and omitted when creating, so the
   * current version has one definition - in `backend/app/agents/spec.py` - and
   * the next bump is one edit rather than two repositories agreeing by hand.
   * A spec read at version 2 and saved back keeps its 2: re-saving a draft is
   * not the moment to quietly migrate what somebody published.
   */
  spec_version?: number;
  name: string;
  description?: string | null;
  instructions: string;
  model_profile_id?: string | null;
  model_settings: ModelSettingsSpec;
  capabilities: CapabilityBindingSpec[];
  collection_ids: string[];
  skill_ids: string[];
  context_ids: string[];
  mcp_server_ids: string[];
  /**
   * Delegates, each pinned to a published version.
   *
   * Optional here, always present on the wire - exactly like `notifications`.
   * The field is defaulted server side, so an agent published before delegation
   * existed reads back with an empty list rather than with nothing; it is
   * optional in this type because `create` does not send one.
   */
  subagents?: SubagentRef[];
  /** Model requests one run may make; null uses the platform default of 100. */
  max_steps?: number | null;
  budget?: BudgetSpec | null;
  /**
   * Optional here, required on the wire.
   *
   * The API always answers with a full block - the field is defaulted server
   * side, so an agent published before it existed reads back with the shipped
   * defaults rather than with nothing. It is optional in this type because
   * `create` does not send one, exactly like `spec_version`.
   */
  notifications?: NotificationSpec;
  observability?: ObservabilitySpec | null;
}

export interface Agent {
  id: string;
  slug: string;
  name: string;
  description: string | null;
  status: AgentStatus;
  visibility: Visibility;
  owner_user_id: string | null;
  current_version_id: string | null;
  /** Whether `/api/agents/{id}/avatar` will answer with an image. */
  has_avatar?: boolean;
  /** Chosen default-avatar colour slot (1..10); null/absent is auto from the id. */
  avatar_color?: number | null;
  /**
   * Whether the current caller may run this agent - the floor for creating a
   * trigger, schedule or event on it. Resolved per caller from their role scope
   * and any explicit run grant, so a Viewer granted run on one agent reads true
   * here where the role-level check would say false. Hides create controls; the
   * backend re-checks on every create, so it is not a security boundary.
   */
  can_run: boolean;
  /** How many members hold an explicit grant. Filled by the listing only. */
  shared_user_count?: number;
  /** Surfaces with an active binding ("slack", "telegram", ...). Listing only. */
  channels?: string[];
  /**
   * The published version's monthly cap - the one the runner enforces, not
   * the draft's promise. Null for drafts and uncapped agents. Listing only.
   */
  budget_monthly_usd?: number | null;
  /**
   * How many tokens the model this agent publishes on accepts.
   *
   * What a chat draws its context gauge against. The *share* is resolved where
   * the model is known rather than stored with the reading, because the window
   * belongs to whichever model answers next and the chat lets somebody switch
   * that between turns - a share carried over from a 1M-context model reads
   * "50%" for a history that is really at 390% of a 128K one.
   *
   * Null when neither the profile nor the pricing registry could say, and a
   * surface then draws no share at all rather than one against a guess. Listing
   * only.
   */
  context_window_tokens?: number | null;
  created_at?: string;
  /**
   * `null` until the row is first updated - `TimestampSchema.updated_at` is
   * `datetime | None`, so the API sends the key with a null rather than omitting
   * it. Typed `string | undefined` before, which made the honest test for "never
   * edited" a type error.
   */
  updated_at?: string | null;
}

export interface AgentDetail extends Agent {
  draft_spec: AgentSpec;
}

export interface AgentList {
  items: Agent[];
  total: number;
}

/**
 * One hop of the delegation tree, as `GET /agents/{id}/delegation-tree` answers.
 *
 * `status` says how far the server's walk got: `ok` resolved and `children`
 * holds what the delegate itself delegates to; `restricted` is a delegate the
 * caller may not see - no name, no children, indistinguishable from one that
 * does not exist; `unpinned` is a pin whose version is gone; `cycle` returns to
 * an agent already on this branch and is never expanded; `archived` is a
 * delegate somebody has retired since the pin was published, which every run
 * reaching it is refused for. `truncated` marks a roster a run from this root
 * would never reach.
 */
export interface DelegationTreeNode {
  key: string;
  kind: "delegate" | "specialist";
  status: "ok" | "restricted" | "unpinned" | "cycle" | "archived";
  agent_id: string | null;
  name: string | null;
  mode: DelegationMode | null;
  pinned_version: number | null;
  stale: boolean;
  truncated: boolean;
  children: DelegationTreeNode[];
}

/**
 * The whole delegation tree under one agent's draft, in one response.
 *
 * No `max_depth` / `max_fanout`: the Builder holds the draft those live on and
 * already renders them beside the hub, so a second copy read out of the stored
 * draft would only ever be the half that disagrees.
 */
export interface DelegationTree {
  truncated: boolean;
  nodes: DelegationTreeNode[];
}

/** One named environment of an agent, pinned to one published version. */
export interface AgentEnvironment {
  id: string;
  agent_id: string;
  name: string;
  version_id: string;
  /** The pinned version's number, as the history names it. */
  version: number;
  is_default: boolean;
  /** Which vault key this environment's traces are written with; null = the spec's. */
  logfire_token_secret_id: string | null;
  service_name: string | null;
  created_at: string;
}

export interface AgentEnvironmentList {
  items: AgentEnvironment[];
  total: number;
}

export interface AgentVersion {
  id: string;
  version: number;
  note: string | null;
  published_by_user_id: string | null;
  /**
   * Who published it, resolved server-side.
   *
   * A uuid answers "who changed this" with another question, and that question
   * is the reason a history is read at all. Null means the account has since
   * left the organization - itself an answer worth showing.
   */
  published_by_email?: string | null;
  created_at?: string;
}

/** One version with the spec it froze - what a diff is read from. */
export interface AgentVersionDetail extends AgentVersion {
  spec: AgentSpec;
}

export interface AgentVersionList {
  items: AgentVersion[];
  total: number;
}

/** One tool a capability exposes, as the model is offered it. */
export interface CapabilityTool {
  /** Defined in code and never configurable - what both per-tool maps key on. */
  id: string;
  /**
   * The name the model calls, with this agent's override already applied.
   *
   * The API resolves it, so a client never has to merge the binding into the
   * catalog to know what a run will really offer.
   */
  name: string;
  /** The text the model reads before calling it, override applied the same way. */
  description: string;
}

/**
 * One tool as the *model* meets it.
 *
 * `CapabilityTool` carries the summary line, which is what a list needs. This
 * is the rest - the whole docstring the model reads before deciding to call,
 * and the schema of the arguments. Someone rewording a tool for their agent is
 * rewriting against this, and its first sentence is not it.
 */
export interface CapabilityToolContract {
  tool_id: string;
  description: string;
  /** JSON Schema of the arguments, as the model is given them. */
  parameters: ToolParameterSchema;
}

/** One capability an agent can be given, as the picker shows it. */
export interface CapabilityCatalogEntry {
  id: string;
  name: string;
  category: string;
  description: string;
  side_effecting: boolean;
  scopes: string[];
  /** Empty for a capability that is not tools at all - a guardrail, or instructions. */
  tools: CapabilityTool[];
  /** What each tool above tells the model, in full. Keyed by `tool_id`. */
  contracts: CapabilityToolContract[];
  /** JSON Schema. The configuration form is generated from this, never hand-written. */
  config_schema: JsonSchema | null;
  /**
   * The credential this capability cannot work without, declared as a kind, or
   * null for one that needs none - which is every builtin so far.
   *
   * A binding answers it with `secret_id`. The value itself never reaches the
   * catalog, the spec or the model; only the agent runner ever reads one.
   */
  requires_secret: SecretRequirement | null;
}

export interface CapabilityCatalog {
  items: CapabilityCatalogEntry[];
  total: number;
}

/**
 * A JSON Schema node as a tool's arguments arrive.
 *
 * Wider than `JsonSchema` on purpose: that one is the subset the generated
 * forms can render controls for, and it is allowed to stay small because
 * anything it cannot render is a capability config nobody can fill in. Tool
 * arguments come from a Python signature and are only ever read, so they carry
 * `$ref`, nested `anyOf` and arrays of models that no form has to handle.
 */
export interface ToolParameterSchema {
  type?: string;
  title?: string;
  description?: string;
  properties?: Record<string, ToolParameterSchema>;
  required?: string[];
  items?: ToolParameterSchema;
  anyOf?: ToolParameterSchema[];
  enum?: unknown[];
  $ref?: string;
}

/** The subset of JSON Schema the generated forms understand. */
export interface JsonSchema {
  type?: string;
  title?: string;
  description?: string;
  properties?: Record<string, JsonSchemaProperty>;
  required?: string[];
}

export interface JsonSchemaProperty {
  type?: string | string[];
  title?: string;
  description?: string;
  default?: unknown;
  minimum?: number;
  maximum?: number;
  maxLength?: number;
  enum?: unknown[];
  /**
   * The single value this field may take - a Pydantic `Literal` of one, which
   * is how every secret payload carries its own `kind`. A control for it could
   * only ever be wrong, so the form omits it and the caller supplies it.
   */
  const?: unknown;
  /**
   * JSON Schema's `format`. Only `password` is acted on: Pydantic stamps it
   * onto every `SecretStr`, which is exactly the set of fields that must be
   * masked while they are typed.
   */
  format?: string;
  /**
   * What each enum value is called in a picker, keyed by the value.
   *
   * An extension keyword, because JSON Schema has none for this. Emitted by a
   * capability's `config_schema` through Pydantic's `json_schema_extra`, and
   * there rather than in a table here for the same reason `description` is:
   * `clear_tool_results` in a dropdown says nothing, and a label kept on this
   * side outlives the value it was written for without anyone noticing.
   */
  "x-enum-labels"?: Record<string, string>;
  /**
   * Whether this string is paragraphs rather than a value.
   *
   * An extension keyword, like `x-enum-labels`: Pydantic has no notion of
   * multiline, and a one-line box for a prompt is a field nobody can read what
   * they are editing in.
   */
  "x-multiline"?: boolean;
  /** A `Literal | None` arrives as branches, one carrying the values. */
  anyOf?: {
    type?: string;
    enum?: unknown[];
    format?: string;
    "x-enum-labels"?: Record<string, string>;
  }[];
}
