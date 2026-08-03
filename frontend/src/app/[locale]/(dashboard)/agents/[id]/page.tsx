"use client";

import { use, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  AlertCircle,
  Archive,
  ArchiveRestore,
  Copy,
  Download,
  History,
  ImagePlus,
  MessageSquare,
  MoreHorizontal,
  Network,
  Plug,
  Trash2,
  Upload,
} from "lucide-react";

import { AgentAvatar } from "@/components/agents/agent-avatar";
import { AgentMap, MAP_ICONS, type MapNode } from "@/components/agents/agent-map";
import { AgentStatusBadge } from "@/components/agents/status-badge";
import { AlertsPanel } from "@/components/agents/alerts-panel";
import { CapabilityWorkbench } from "@/components/agents/capability-workbench";
import { WorkspaceSection } from "@/components/agents/workspace-section";
import { ChannelBotsPanel } from "@/components/agents/channel-bots-panel";
import { CollectionPicker } from "@/components/agents/collection-picker";
import { EmbedsPanel } from "@/components/agents/embeds-panel";
import { ExposuresPanel } from "@/components/agents/exposures-panel";
import { McpServerPicker } from "@/components/agents/mcp-server-picker";
import { McpServerList } from "@/components/mcp/mcp-server-list";
import { ModelProfilePicker } from "@/components/agents/model-profile-picker";
import { ObservabilityCard } from "@/components/agents/observability-card";
import { RunSummary } from "@/components/agents/run-summary";
import { ModelSettingsForm } from "@/components/agents/model-settings-form";
import { SkillGallery } from "@/components/agents/skill-gallery";
import { ThinkingSetting } from "@/components/agents/thinking-setting";
import { EnvironmentsPanel } from "@/components/agents/environments-panel";
import { VersionHistory } from "@/components/agents/version-history";
import { PageHeader } from "@/components/dashboard/page-header";
import { SharingPanel } from "@/components/sharing/sharing-panel";
import {
  Badge,
  Button,
  ConfirmDialog,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Input,
  Label,
  MarkdownEditor,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui";
import {
  useAgent,
  useAgentEnvironments,
  useAgents,
  useAgentVersions,
  useCapabilityCatalog,
  useExposures,
  useKnowledgeBases,
  useMcpCatalog,
  useModelProviders,
  useOrgMcpConnections,
  usePermissions,
  useRuns,
  useSkills,
} from "@/hooks";
import { SANDBOX_ID, SKILLS_ID, THINKING_ID, withCapability, withSkills } from "@/lib/agent-spec";
import { ROUTES } from "@/lib/constants";
import { useAgentSelectionStore, useConversationStore } from "@/stores";
import { cn } from "@/lib/utils";
import type { AgentSpec, CapabilityBindingSpec } from "@/types/agents";
import { Perm } from "@/types/permissions";

interface PageProps {
  params: Promise<{ id: string }>;
}

export default function AgentBuilderPage({ params }: PageProps) {
  const { id } = use(params);
  const router = useRouter();
  const { agent, isLoading, saveDraft, validate, publish, rollback, setAvatar } = useAgent(id);
  const { environments, promote } = useAgentEnvironments(id);
  const { clone, archive, unarchive, remove } = useAgents();
  const { capabilities } = useCapabilityCatalog();
  const { profiles } = useModelProviders();
  // The Builder holds the set rather than paging it: the gallery has to know
  // which selected skills still exist, and it can only tell that from what it
  // has. 100 is the endpoint's ceiling; `total` says when that is not all.
  const { skills, total: skillCount } = useSkills({ limit: 100 });
  const { kbs: collections } = useKnowledgeBases();
  const { versions } = useAgentVersions(id);
  const { runs } = useRuns(id);
  const { can } = usePermissions();
  // The organization's servers, never the author's own: a personal connection
  // is refused at publish, so offering one would be offering a choice that
  // cannot be published. `useMcpCatalog` only supplies the names and logos -
  // the ids the spec stores belong to the connections.
  const { connections: mcpConnections } = useOrgMcpConnections();
  const { exposures } = useExposures(id);
  const { servers: mcpCatalog } = useMcpCatalog();
  const selectAgentForChat = useAgentSelectionStore((state) => state.select);
  const resetConversation = useConversationStore((state) => state.reset);

  const [spec, setSpec] = useState<AgentSpec | null>(null);
  const [problems, setProblems] = useState<string[]>([]);
  const [confirming, setConfirming] = useState<"archive" | "delete" | null>(null);
  const [mapOpen, setMapOpen] = useState(false);
  const [connectingMcp, setConnectingMcp] = useState(false);
  // Bumped after an upload so the <img> src changes; the URL is otherwise
  // identical and the browser would keep showing the picture it replaced.
  const [avatarVersion, setAvatarVersion] = useState(0);
  const avatarInput = useRef<HTMLInputElement>(null);

  // Adopt the server's draft whenever there is nothing local, and not
  // otherwise: every autosave invalidates the agent query, and re-adopting the
  // answer would overwrite whatever was typed while the save was in flight.
  // `setSpec(null)` is how a flow that really does replace the draft (rollback)
  // asks to adopt again - so the condition is the absent spec, not a changed
  // draft. Rolling back to a version structurally equal to the current draft
  // leaves React Query holding the same reference, and gating on the reference
  // moving left the page on its skeleton with no way out.
  if (agent?.draft_spec && spec === null) {
    setSpec(agent.draft_spec);
  }

  const canEdit = can(Perm.agentsEdit);
  const canPublish = can(Perm.agentsPublish);

  // A draft differs from what is live the moment anything is edited. Showing
  // that difference is what stops someone testing a change that never shipped.
  const isDirty = useMemo(
    () => JSON.stringify(spec) !== JSON.stringify(agent?.draft_spec),
    [spec, agent?.draft_spec],
  );

  // The draft stores itself. A Builder with a Save button is a Builder where
  // the tab closed on twenty minutes of instructions; the debounce means a
  // burst of typing is one request.
  //
  // `storing` is a dependency because a save *settling* is what decides whether
  // another is owed, and nothing else reports it. This effect used to depend on
  // the edit alone and claim it re-armed "after every invalidation until the
  // spec and the stored draft agree" - which it did not: when a save does not
  // land, the refetch that follows returns data deeply equal to what is cached,
  // React Query hands back the same object, and no dependency here changes. One
  // missed save therefore left the Builder saying "Unsaved" for as long as the
  // page stayed open, with nothing retrying and nothing else to click, until
  // the next edit happened to carry the lost one along.
  //
  // Two attempts per distinct spec, and the count is per payload rather than
  // per render: the second covers a save that failed or did not take, and
  // stopping there keeps a spec the API genuinely refuses from becoming a
  // request every 1.2 seconds. When both are spent the badge keeps saying
  // "Unsaved", which by then is the truth.
  const { mutateAsync: storeDraft, isPending: storing } = saveDraft;
  const attempts = useRef<{ payload: string; tries: number }>({ payload: "", tries: 0 });
  useEffect(() => {
    if (!canEdit || !spec || !agent?.draft_spec || !isDirty || storing) return;
    const payload = JSON.stringify(spec);
    if (payload === attempts.current.payload && attempts.current.tries >= 2) return;
    const timer = setTimeout(() => {
      attempts.current =
        payload === attempts.current.payload
          ? { payload, tries: attempts.current.tries + 1 }
          : { payload, tries: 1 };
      // Errors already toast in the hook; the badge only needs to keep saying
      // "unsaved", which `isDirty` staying true does on its own.
      void storeDraft(spec).catch(() => null);
    }, 1200);
    return () => clearTimeout(timer);
  }, [spec, agent?.draft_spec, isDirty, canEdit, storeDraft, storing]);

  // Names, never ids: the map exists to be read, and a row of uuids is the
  // thing it replaces. Anything the spec references but the organization no
  // longer has is named as missing rather than dropped - a silently shorter
  // list hides exactly the problem that refuses at publish.
  const mapNodes = useMemo<MapNode[]>(() => {
    if (!spec) return [];
    const name = <T extends { id: string; name: string }>(pool: T[], id: string) =>
      pool.find((entry) => entry.id === id)?.name ?? `${id} (missing)`;
    const chosen = profiles.find((entry) => entry.id === spec.model_profile_id);
    const profile = spec.model_profile_id
      ? chosen
        ? `${chosen.label} · ${chosen.model}`
        : `${spec.model_profile_id} (missing)`
      : "Organization default";

    return [
      {
        key: "channels",
        title: "Channels",
        icon: MAP_ICONS.channels,
        side: "in",
        items: exposures.map(
          (exposure) => `${exposure.channel_bot_name}${exposure.is_active ? "" : " (paused)"}`,
        ),
        empty: "Chat only - not on Slack or Telegram",
      },
      {
        key: "knowledge",
        title: "Knowledge",
        icon: MAP_ICONS.knowledge,
        side: "in",
        items: spec.collection_ids.map((entry) => name(collections, entry)),
        empty: "No collections attached",
      },
      {
        key: "model",
        title: "Model",
        icon: MAP_ICONS.model,
        side: "out",
        items: [profile],
        empty: "No model",
      },
      {
        key: "capabilities",
        title: "Toolbox",
        icon: MAP_ICONS.capabilities,
        side: "out",
        items: spec.capabilities
          .filter((binding) => binding.enabled)
          .map((binding) => name(capabilities, binding.id)),
        empty: "No capabilities enabled",
      },
      {
        key: "mcp",
        title: "MCP servers",
        icon: MAP_ICONS.mcp,
        side: "out",
        items: spec.mcp_server_ids.map((entry) => name(mcpConnections, entry)),
        empty: "No MCP servers attached",
      },
      {
        key: "skills",
        title: "Skills",
        icon: MAP_ICONS.skills,
        side: "out",
        items: spec.skill_ids.map((entry) => name(skills, entry)),
        empty: "No skills attached",
      },
      {
        key: "budget",
        title: "Budget",
        icon: MAP_ICONS.budget,
        side: "out",
        items: spec.budget?.monthly_usd ? [`$${spec.budget.monthly_usd} per month`] : [],
        empty: "Spends without a ceiling of its own",
      },
    ];
  }, [spec, exposures, collections, profiles, capabilities, mcpConnections, skills]);

  // Two capabilities are configured elsewhere and so are kept off this list,
  // because a second control for one field is a control that disagrees with the
  // first. Thinking sits with the model settings: it contributes no tools and
  // changes how the model runs, not what the agent can do. Skills sits in its
  // own section, which owns both halves of a decision that used to be split -
  // see `setSkills`. The workspace has one too: it is a choice between four
  // backends rather than a switch, and one of its scopes shares files between
  // people.
  const grantable = useMemo(
    () =>
      capabilities.filter(
        (entry) => entry.id !== THINKING_ID && entry.id !== SKILLS_ID && entry.id !== SANDBOX_ID,
      ),
    [capabilities],
  );

  if (isLoading || !spec || !agent) return <BuilderSkeleton />;

  const isPublished = agent.status === "published";

  const update = (changes: Partial<AgentSpec>) => setSpec({ ...spec, ...changes });

  const toggleCapability = (capabilityId: string) => {
    const on = spec.capabilities.some((binding) => binding.id === capabilityId);
    update({ capabilities: withCapability(spec.capabilities, capabilityId, !on) });
  };

  const updateCapability = (updated: CapabilityBindingSpec) =>
    update({
      capabilities: spec.capabilities.map((capability) =>
        capability.id === updated.id ? updated : capability,
      ),
    });

  const toggleId = (list: string[], value: string) =>
    list.includes(value) ? list.filter((item) => item !== value) : [...list, value];

  const setSkills = (skillIds: string[]) => update(withSkills(spec, skillIds));

  /**
   * Store the draft, and stop if it did not store.
   *
   * `validate` asks the server about the draft it holds, so running it after a
   * failed save reports on a spec nobody is looking at - and reports it as the
   * verdict on the one on screen. `saveDraft` has already said what went wrong.
   */
  async function persist(): Promise<boolean> {
    if (!spec) return false;
    try {
      await saveDraft.mutateAsync(spec);
      return true;
    } catch {
      return false;
    }
  }

  async function handlePublish() {
    if (!(await persist())) return;
    const found = await validate();
    setProblems(found);
    if (found.length === 0) await publish.mutateAsync(null);
  }

  /**
   * Address the chat to this agent, then open it on a fresh thread.
   *
   * Selecting first is the whole point: the chat sends whichever agent the
   * selection names. Resetting the conversation matters just as much - the
   * store keeps whichever thread was open last, and landing in an old
   * conversation reads as the agent answering with somebody else's context.
   */
  function openInChat() {
    selectAgentForChat(id);
    resetConversation();
    router.push(ROUTES.CHAT);
  }

  async function handleAvatar(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    // Cleared before awaiting, so picking the same file twice in a row still
    // fires a change event - otherwise a failed upload cannot be retried with
    // the same image.
    event.target.value = "";
    if (!file) return;
    await setAvatar.mutateAsync(file).catch(() => null);
    setAvatarVersion((version) => version + 1);
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title={
          <span className="flex items-center gap-3">
            <span className="group relative">
              <AgentAvatar
                agentId={id}
                name={agent.name}
                hasAvatar={agent.has_avatar}
                size="lg"
                version={avatarVersion}
              />
              {canEdit && (
                <button
                  type="button"
                  onClick={() => avatarInput.current?.click()}
                  disabled={setAvatar.isPending}
                  aria-label={agent.has_avatar ? "Replace avatar" : "Upload avatar"}
                  title="Square images look best. Up to 2MB."
                  className="bg-background/70 text-foreground absolute inset-0 flex items-center justify-center rounded-full opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100 disabled:cursor-not-allowed"
                >
                  <ImagePlus className="h-5 w-5" />
                </button>
              )}
            </span>
            {agent.name}
            <AgentStatusBadge status={agent.status} />
            {/* The draft saves itself; this says where that stands. Quiet when
                everything is stored - "saved" as a permanent label reads as a
                button. */}
            {canEdit &&
              (saveDraft.isPending ? (
                <Badge variant="secondary">Saving…</Badge>
              ) : (
                isDirty && <Badge variant="secondary">Unsaved</Badge>
              ))}
          </span>
        }
        description={agent.description ?? undefined}
        breadcrumbs={[{ label: "Agents", href: ROUTES.AGENTS }, { label: agent.name }]}
        actions={
          <div className="flex items-center gap-2">
            {/* Trying the agent happens in the chat, which streams, keeps the
                conversation and can hand a tool call to the approval queue.
                Only a published agent has a version to run - the chat's own
                picker offers no others - so a draft says what unlocks it
                instead of opening a chat that would answer as somebody else. */}
            <Button
              variant="outline"
              onClick={openInChat}
              disabled={!isPublished}
              title={
                isPublished
                  ? undefined
                  : "Publish this agent to chat with it - the chat runs the published version"
              }
            >
              <MessageSquare className="h-4 w-4" />
              Open in chat
            </Button>
            {/* Beside the chat button rather than in the overflow menu: the
                map answers "what is this agent" and that question comes up
                before publishing, not after somebody goes looking for it. */}
            <Button variant="outline" onClick={() => setMapOpen(true)}>
              <Network className="h-4 w-4" />
              Visual map
            </Button>
            <Button variant="outline" asChild>
              <a href={`/api/agents/${id}/spec.yaml`} download>
                <Download className="h-4 w-4" />
                Export YAML
              </a>
            </Button>
            {canPublish && (
              <Button onClick={handlePublish} disabled={publish.isPending}>
                <Upload className="h-4 w-4" />
                Publish
              </Button>
            )}
            {canEdit && (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="outline" size="icon" aria-label="More actions">
                    <MoreHorizontal className="h-4 w-4" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem
                    onSelect={() =>
                      clone.mutate(id, {
                        onSuccess: (created) => router.push(ROUTES.AGENT_DETAIL(created.id)),
                      })
                    }
                  >
                    <Copy className="h-4 w-4" />
                    Duplicate
                  </DropdownMenuItem>
                  <DropdownMenuItem onSelect={() => avatarInput.current?.click()}>
                    <ImagePlus className="h-4 w-4" />
                    {agent.has_avatar ? "Replace avatar" : "Upload avatar"}
                  </DropdownMenuItem>
                  {agent.status === "archived" ? (
                    <DropdownMenuItem onSelect={() => unarchive.mutate(id)}>
                      <ArchiveRestore className="h-4 w-4" />
                      Restore
                    </DropdownMenuItem>
                  ) : (
                    <DropdownMenuItem onSelect={() => setConfirming("archive")}>
                      <Archive className="h-4 w-4" />
                      Archive
                    </DropdownMenuItem>
                  )}
                  <DropdownMenuSeparator />
                  <DropdownMenuItem
                    className="text-destructive focus:text-destructive"
                    onSelect={() => setConfirming("delete")}
                  >
                    <Trash2 className="h-4 w-4" />
                    Delete permanently
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            )}
            <input
              ref={avatarInput}
              type="file"
              accept="image/png,image/jpeg,image/webp,image/gif"
              className="hidden"
              onChange={handleAvatar}
            />
          </div>
        }
      />

      <Dialog open={mapOpen} onOpenChange={setMapOpen}>
        <DialogContent className="max-h-[92vh] overflow-y-auto sm:max-w-[80rem]">
          <DialogHeader>
            <DialogTitle>Visual map</DialogTitle>
            <DialogDescription>
              The draft as it stands: what reaches this agent, and what it reaches for. A dashed box
              is something nothing is attached to.
            </DialogDescription>
          </DialogHeader>
          {spec && (
            <AgentMap agentName={spec.name} instructions={spec.instructions} nodes={mapNodes} />
          )}
        </DialogContent>
      </Dialog>

      {/* The catalog itself, not a second connect form beside it. `McpServerList`
          reads and writes the same query cache the picker above does, so a server
          connected in here appears in the picker as soon as the dialog closes -
          without a refetch, and without this page knowing how a connection is
          made. */}
      <Dialog open={connectingMcp} onOpenChange={setConnectingMcp}>
        <DialogContent className="max-h-[92vh] overflow-y-auto sm:max-w-[72rem]">
          <DialogHeader>
            <DialogTitle>Connect an MCP server</DialogTitle>
            <DialogDescription>
              Connect a server for the organization and it becomes bindable here. A personal
              connection is for your own chat and is refused at publish, so an agent everyone runs
              never depends on whose credential is behind it.
            </DialogDescription>
          </DialogHeader>
          <McpServerList canManageOrganization={can(Perm.connectionsManage)} />
        </DialogContent>
      </Dialog>

      {confirming === "archive" && (
        <ConfirmDialog
          open
          onOpenChange={() => setConfirming(null)}
          title={`Archive ${agent.name}?`}
          description="It stops answering everywhere it is available. Its versions, runs and history are kept, and it can be restored."
          confirmLabel="Archive"
          loading={archive.isPending}
          onConfirm={async () => {
            await archive.mutateAsync(id);
            setConfirming(null);
          }}
        />
      )}

      {confirming === "delete" && (
        <ConfirmDialog
          open
          onOpenChange={() => setConfirming(null)}
          title={`Delete ${agent.name}?`}
          description="This removes the agent, every version of it and every share pointing at it. Its past runs are kept for the record. Archive instead if you only want it to stop."
          confirmLabel="Delete"
          confirmText={agent.slug}
          destructive
          loading={remove.isPending}
          onConfirm={async () => {
            await remove.mutateAsync(id);
            router.push(ROUTES.AGENTS);
          }}
        />
      )}

      {problems.length > 0 && (
        <Card className="border-destructive/40 bg-destructive/5">
          <CardContent className="space-y-2 p-4">
            <p className="flex items-center gap-2 text-sm font-medium">
              <AlertCircle className="h-4 w-4" />
              This agent cannot be published yet
            </p>
            <ul className="text-muted-foreground list-inside list-disc space-y-1 text-sm">
              {problems.map((problem) => (
                <li key={problem}>{problem}</li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}

      {/* Tabs, because the alternative was a single column of eleven cards and
          a page of scroll between the instructions and the version history.
          Grouped by the question being answered, not by implementation. */}
      <Tabs defaultValue="build">
        <TabsList>
          <TabsTrigger value="build">Build</TabsTrigger>
          <TabsTrigger value="toolbox">Toolbox</TabsTrigger>
          <TabsTrigger value="knowledge">Knowledge</TabsTrigger>
          <TabsTrigger value="skills">Skills</TabsTrigger>
          <TabsTrigger value="limits">Limits</TabsTrigger>
          <TabsTrigger value="availability">Availability</TabsTrigger>
          <TabsTrigger value="history">History</TabsTrigger>
        </TabsList>

        <TabsContent value="build" className="mt-4 space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>Instructions</CardTitle>
              <CardDescription>
                The agent&apos;s behaviour lives here, not in code. Be specific about what it should
                do, what it should refuse, and how it should cite. Markdown, and the model reads the
                structure - headings and lists are what make a long prompt followable, so being able
                to see them rendered is the point of the preview.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <MarkdownEditor
                // Named, because a placeholder is not a label: it is the only
                // accessible name this control had, and it is the one thing that
                // disappears the moment somebody types into it.
                label="Instructions"
                value={spec.instructions}
                onChange={(instructions) => update({ instructions })}
                rows={10}
                disabled={!canEdit}
                placeholder="You are Support Copilot. Answer from the product wiki and cite the document you used. If the wiki does not cover it, say so rather than guessing."
              />
              <div className="space-y-2">
                <Label>Model</Label>
                <ModelProfilePicker
                  allowAdd
                  profiles={profiles}
                  value={spec.model_profile_id ?? null}
                  onChange={(model_profile_id) => update({ model_profile_id })}
                  disabled={!canEdit}
                />
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Model settings</CardTitle>
              <CardDescription>
                How this agent asks its model to behave, on top of whatever the model profile
                already sets. A setting nobody touches is not sent at all - that is deliberate
                rather than tidy: reasoning models reject a temperature outright, so an agent that
                never chose one must not have one sent on its behalf. A provider that does not
                implement a setting ignores it. Reasoning itself is a capability, below.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <ModelSettingsForm
                value={spec.model_settings}
                onChange={(model_settings) => update({ model_settings })}
                disabled={!canEdit}
              />
              <ThinkingSetting
                definition={capabilities.find((entry) => entry.id === THINKING_ID)}
                binding={spec.capabilities.find((binding) => binding.id === THINKING_ID)}
                onToggle={() => toggleCapability(THINKING_ID)}
                onChange={updateCapability}
                disabled={!canEdit}
              />
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="toolbox" className="mt-4 space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>Capabilities</CardTitle>
              <CardDescription>
                What this agent can do, and where it keeps what it produces. Anything that acts on
                the outside world needs a human approval before it runs.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              {/* Above the picker, and inside the same card: the workspace is
                  where the tools below put things, so reading it first is the
                  order somebody configures in. It keeps its own controls rather
                  than becoming a row - four backends with different
                  infrastructure behind them, one of which shares files between
                  people, is not the same kind of decision as switching on a
                  chart tool. */}
              <div className="space-y-3">
                <div className="space-y-1">
                  <h3 className="text-sm font-medium">Workspace</h3>
                  <p className="text-muted-foreground text-sm">
                    Where this agent keeps files between turns, and who else can read them.
                    Attachments land here too, so a large file stops being pasted into every
                    message.
                  </p>
                </div>
                <WorkspaceSection
                  definition={capabilities.find((entry) => entry.id === SANDBOX_ID)}
                  binding={spec.capabilities.find((binding) => binding.id === SANDBOX_ID)}
                  onToggle={toggleCapability}
                  onChange={updateCapability}
                  disabled={!canEdit}
                />
              </div>

              <div className="border-border border-t pt-6">
                <CapabilityWorkbench
                  catalog={grantable}
                  selected={spec.capabilities}
                  onToggle={toggleCapability}
                  onChange={updateCapability}
                  disabled={!canEdit}
                />
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0 space-y-1.5">
                  <CardTitle>MCP servers</CardTitle>
                  <CardDescription>
                    External tools this agent may call, from the servers{" "}
                    <Link href={ROUTES.MCP_SERVERS} className="underline">
                      your organization has connected
                    </Link>
                    . Only the organization&apos;s servers appear here - an agent everyone runs
                    cannot depend on whose credential is behind it, so a personal connection is
                    refused at publish.
                  </CardDescription>
                </div>
                {/* Connecting a server was a different page, and the trip was
                    the problem: the moment you need one is while binding tools
                    to an agent, and leaving the Builder to get it meant leaving
                    an unsaved draft. The dialog holds the real catalog rather
                    than a second copy of the connect form - one flow, one set
                    of refusals, and the connection it creates lands in the same
                    cache this picker reads. */}
                {can(Perm.connectionsManage) && (
                  <Button variant="outline" size="sm" onClick={() => setConnectingMcp(true)}>
                    <Plug className="h-3.5 w-3.5" />
                    Connect a server
                  </Button>
                )}
              </div>
            </CardHeader>
            <CardContent>
              <McpServerPicker
                connections={mcpConnections}
                catalog={mcpCatalog}
                selectedIds={spec.mcp_server_ids}
                onToggle={(connectionId) =>
                  update({ mcp_server_ids: toggleId(spec.mcp_server_ids, connectionId) })
                }
                disabled={!canEdit}
              />
              <p className="text-muted-foreground mt-4 text-xs">
                Two limits worth knowing before you rely on this. Which of a server&apos;s tools are
                exposed is set on the connection, so every agent bound to it gets the same ones -
                not the per-agent choice the capabilities above offer. And MCP tools are outside the
                approval gate entirely: an approval set on a capability does not cover them, so
                anything these servers can do, this agent can do without asking.
              </p>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="knowledge" className="mt-4 space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>Collections</CardTitle>
              <CardDescription>
                What this agent may search. The model chooses what to look for; it can never widen
                where it looks. Each collection says what it holds, because attaching an empty one
                produces an agent that searches, finds nothing, and reads as broken.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <CollectionPicker
                collections={collections}
                selectedIds={spec.collection_ids}
                onToggle={(collectionId) =>
                  update({ collection_ids: toggleId(spec.collection_ids, collectionId) })
                }
                disabled={!canEdit}
              />
            </CardContent>
          </Card>
        </TabsContent>

        {/* Its own tab rather than a card under Knowledge. A collection is
            something the agent searches; a skill is something it reads and then
            acts on. Sharing a tab made the gallery look like a second picker for
            the same decision, and put the two things with the most to read on
            one scroll. */}
        <TabsContent value="skills" className="mt-4 space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>Skills</CardTitle>
              <CardDescription>
                Written know-how the agent loads only when it decides a skill is relevant, so twenty
                skills cost almost nothing in context. Picking one gives the agent the tools to read
                them - that used to be a separate capability somebody had to know to switch on, and
                skills chosen without it were resolved and then dropped on the floor.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <SkillGallery
                skills={skills}
                total={skillCount}
                selectedIds={spec.skill_ids}
                onToggle={(skillId) => setSkills(toggleId(spec.skill_ids, skillId))}
                disabled={!canEdit}
              />
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="limits" className="mt-4 space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>Run limits</CardTitle>
              <CardDescription>
                This agent&apos;s own monthly spending limit. The organization&apos;s limit still
                applies on top - an agent can tighten it, never loosen it. The step limit catches
                the other kind of runaway: a tool loop that is cheap per call and never finishes.
              </CardDescription>
            </CardHeader>
            <CardContent className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="monthly">Monthly (USD)</Label>
                <Input
                  id="monthly"
                  type="number"
                  step="1"
                  min="0"
                  value={spec.budget?.monthly_usd ?? ""}
                  disabled={!canEdit}
                  onChange={(event) =>
                    update({
                      budget: {
                        ...spec.budget,
                        monthly_usd: event.target.value ? Number(event.target.value) : null,
                      },
                    })
                  }
                  placeholder="No limit"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="max-steps">Max steps per run</Label>
                <Input
                  id="max-steps"
                  type="number"
                  step="1"
                  min="1"
                  max="200"
                  value={spec.max_steps ?? ""}
                  disabled={!canEdit}
                  onChange={(event) =>
                    update({ max_steps: event.target.value ? Number(event.target.value) : null })
                  }
                  placeholder="100 (default)"
                />
                <p className="text-muted-foreground text-xs">
                  How many model requests one run may make. A tool loop hits this long before it
                  costs enough to hit a budget.
                </p>
              </div>
            </CardContent>
          </Card>
          {/* Beside the budget rather than in a settings page of its own: the two
              questions are "how much may this agent spend" and "who is told when
              it stops", and answering the first without the second is how a run
              stops quietly. */}
          <AlertsPanel
            value={spec.notifications}
            onChange={(notifications) => update({ notifications })}
            disabled={!canEdit}
          />
          <ObservabilityCard
            value={spec.observability}
            onChange={(observability) => update({ observability })}
            disabled={!canEdit}
            agentName={spec.name}
          />
        </TabsContent>

        <TabsContent value="availability" className="mt-4 space-y-6">
          <ExposuresPanel agentId={id} canManage={canPublish} />
          {/* Bots stay organization resources - one bot serves many agents -
              but they are registered here, beside the binding they exist for.
              The panel hides itself from anyone without channels:manage. */}
          <ChannelBotsPanel canManage={can(Perm.channelsManage)} />
          <EmbedsPanel agentId={id} canManage={canPublish} />
          <SharingPanel resourceType="agent" resourceId={id} canManage={canEdit} />
        </TabsContent>

        <TabsContent value="history" className="mt-4 space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>Environments</CardTitle>
              <CardDescription>
                Named pointers at published versions. Publish moves only the default; every other
                environment stays pinned until a version is promoted onto it from the list below. A
                bot bound to an environment serves its version.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <EnvironmentsPanel agentId={id} canManage={canPublish} />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <History className="h-4 w-4" />
                Versions
              </CardTitle>
              <CardDescription>
                Each publish freezes a spec. Runs record the version, so what an agent did last
                Tuesday stays answerable after a dozen edits. Restoring publishes a new version
                copied from the old one - the timeline shows that a rollback happened rather than
                pretending the bad version never existed.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-2">
              <VersionHistory
                agentId={id}
                versions={versions}
                currentVersionId={agent.current_version_id}
                draftSpec={spec}
                canRestore={canPublish}
                onRestore={(versionId) =>
                  // Restoring replaces the draft server-side; clearing the local
                  // spec is the once-only adoption effect's cue to take the new one.
                  rollback.mutate(versionId, { onSuccess: () => setSpec(null) })
                }
                restoring={rollback.isPending}
                environments={environments}
                onPromote={(environmentId, versionId) =>
                  promote.mutate({ environmentId, versionId })
                }
                promoting={promote.isPending}
              />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Recent runs</CardTitle>
              <CardDescription>
                Whether this agent is working, and what it has cost. The full history - surfaces,
                tokens, the version each run executed - lives in Activity rather than being
                half-rebuilt here.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <RunSummary agentId={id} runs={runs} />
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}

/**
 * The Builder's own skeleton.
 *
 * None of the shared variants fit: this page is a breadcrumbed header with four
 * actions, a seven-tab strip, and a card whose body is dominated by a ten-row
 * textarea. Approximating that with a card grid would move the tab strip the
 * moment the agent arrived, which is the jump the skeleton exists to prevent.
 * `ConversationSkeleton` in `chat-container.tsx` is the same argument.
 */
function BuilderSkeleton() {
  return (
    <div role="status" aria-label="Loading" className="space-y-6">
      <div className="mb-6 md:mb-8">
        <div className="bg-foreground/8 mb-3 h-3 w-40 animate-pulse rounded" />
        <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div className="min-w-0 space-y-2">
            <div className="bg-foreground/10 h-5 w-52 animate-pulse rounded" />
            <div className="bg-foreground/8 h-3.5 w-80 max-w-full animate-pulse rounded" />
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {["w-32", "w-28", "w-24", "w-20"].map((width) => (
              <div
                key={width}
                className={cn("bg-foreground/10 h-9 animate-pulse rounded-md", width)}
              />
            ))}
          </div>
        </div>
      </div>

      {/* Tab strip - seven tabs, at the widths their labels take. */}
      <div className="bg-muted inline-flex h-9 items-center gap-1 rounded-lg p-1">
        {["w-12", "w-20", "w-24", "w-16", "w-16", "w-24", "w-16"].map((width) => (
          <div key={width} className={cn("bg-foreground/10 h-7 animate-pulse rounded-md", width)} />
        ))}
      </div>

      <Card>
        <CardHeader className="space-y-2">
          <div className="bg-foreground/10 h-4 w-28 animate-pulse rounded" />
          <div className="bg-foreground/8 h-3 w-full max-w-xl animate-pulse rounded" />
        </CardHeader>
        <CardContent className="space-y-4">
          {/* The instructions textarea: rows={10} at the same border and radius. */}
          <div className="border-input bg-foreground/[0.04] h-52 animate-pulse rounded-md border" />
          <div className="space-y-2">
            <div className="bg-foreground/10 h-3 w-16 animate-pulse rounded" />
            <div className="border-input bg-foreground/[0.04] h-9 w-full animate-pulse rounded-md border" />
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
