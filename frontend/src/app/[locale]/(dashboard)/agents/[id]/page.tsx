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
import { AgentMap, MAP_ICONS, type MapDelegate, type MapNode } from "@/components/agents/agent-map";
import { MODE_LABEL } from "@/components/agents/agent-map-nodes";
import { toMapDelegates } from "@/components/agents/agent-map-tree";
import { AgentStatusBadge } from "@/components/agents/status-badge";
import { AlertsPanel } from "@/components/agents/alerts-panel";
import { CapabilityWorkbench } from "@/components/agents/capability-workbench";
import { CollectionPicker } from "@/components/agents/collection-picker";
import { EmbedsPanel } from "@/components/agents/embeds-panel";
import { ExposuresPanel } from "@/components/agents/exposures-panel";
import { McpServerPicker } from "@/components/agents/mcp-server-picker";
import { McpServerList } from "@/components/mcp/mcp-server-list";
import { ModelProfilePicker } from "@/components/agents/model-profile-picker";
import { ObservabilityCard } from "@/components/agents/observability-card";
import { PublishDialog } from "@/components/agents/publish-dialog";
import { PublishState } from "@/components/agents/publish-state";
import { RunSummary } from "@/components/agents/run-summary";
import { ModelSettingsForm } from "@/components/agents/model-settings-form";
import { SkillGallery } from "@/components/agents/skill-gallery";
import { ContextGallery } from "@/components/agents/context-gallery";
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
  AvatarColorPicker,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
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
  useDelegationTree,
  useEmbeds,
  useExposures,
  useKnowledgeBases,
  useMcpCatalog,
  useModelProviders,
  useOrgMcpConnections,
  usePermissions,
  useRuns,
  useSkills,
} from "@/hooks";
import {
  readSubagentsConfig,
  SANDBOX_ID,
  SKILLS_ID,
  SUBAGENTS_ID,
  THINKING_ID,
  withCapability,
  withContextFiles,
  withSkills,
} from "@/lib/agent-spec";
import { useContextFiles } from "@/hooks/use-context";
import { ROUTES } from "@/lib/constants";
import { useAgentSelectionStore, useConversationStore } from "@/stores";
import { cn } from "@/lib/utils";
import type { AgentSpec, CapabilityBindingSpec } from "@/types/agents";
import { Perm } from "@/types/permissions";
import { useTranslations } from "next-intl";

interface PageProps {
  params: Promise<{ id: string }>;
}

export default function AgentBuilderPage({ params }: PageProps) {
  const t = useTranslations("pages.agents");
  const tc = useTranslations("common");
  const tAgents = useTranslations("agents");
  const { id } = use(params);
  const router = useRouter();
  const { agent, isLoading, saveDraft, validate, publish, rollback, setAvatar, setColor } =
    useAgent(id);
  const { environments, promote } = useAgentEnvironments(id);
  const { agents, clone, archive, unarchive, remove } = useAgents();
  const { capabilities } = useCapabilityCatalog();
  const { profiles, profilesStatus } = useModelProviders();
  // The Builder holds the set rather than paging it: the gallery has to know
  // which selected skills still exist, and it can only tell that from what it
  // has. 100 is the endpoint's ceiling; `total` says when that is not all.
  const { skills, total: skillCount } = useSkills({ limit: 100 });
  const { files: contextFiles, total: contextCount } = useContextFiles({ limit: 100 });
  const { kbs: collections } = useKnowledgeBases();
  const { versions } = useAgentVersions(id);
  const { runs } = useRuns(id);
  const { can, isLoaded: permissionsLoaded } = usePermissions();
  // The organization's servers, never the author's own: a personal connection
  // is refused at publish, so offering one would be offering a choice that
  // cannot be published. `useMcpCatalog` only supplies the names and logos -
  // the ids the spec stores belong to the connections.
  const { connections: mcpConnections } = useOrgMcpConnections();
  const { exposures } = useExposures(id);
  const { embeds } = useEmbeds(id);
  const { servers: mcpCatalog } = useMcpCatalog();
  const selectAgentForChat = useAgentSelectionStore((state) => state.select);
  const resetConversation = useConversationStore((state) => state.reset);

  const [spec, setSpec] = useState<AgentSpec | null>(null);
  const [problems, setProblems] = useState<string[]>([]);
  const [confirming, setConfirming] = useState<"archive" | "delete" | null>(null);
  const [publishOpen, setPublishOpen] = useState(false);
  const [mapOpen, setMapOpen] = useState(false);
  // Fetched only while the map shows it: the server resolves and
  // access-checks every pinned version to build this.
  const {
    tree,
    isLoading: treeLoading,
    error: treeError,
  } = useDelegationTree(id, { enabled: mapOpen });
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

  // A builder who cannot add a model, in an organization that has none, can
  // create a draft they can never make work. Both halves are read from a
  // *settled* query rather than from "no longer loading": a profiles read that
  // failed or is still in flight also answers `[]` - hence `"loaded"` rather
  // than "not pending" - and `can()` answers false until the set is in, so
  // either alone tells a caller who has models, or who may add one, they are stuck.
  const modelDeadEnd =
    profilesStatus === "loaded" &&
    profiles.length === 0 &&
    permissionsLoaded &&
    !can(Perm.connectionsManage);

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
  //
  // Four directions, each its own question (#518): what reaches the agent on
  // the left, what it runs as on top, what it reaches for on the right, and
  // what it hands work to at the bottom.
  const mapNodes = useMemo<MapNode[]>(() => {
    if (!spec) return [];
    const name = <T extends { id: string; name: string }>(pool: T[], id: string) =>
      pool.find((entry) => entry.id === id)?.name ?? t("namedMissing", { name: id });
    const chosen = profiles.find((entry) => entry.id === spec.model_profile_id);
    const profile = spec.model_profile_id
      ? chosen
        ? `${chosen.label} · ${chosen.model}`
        : t("namedMissing", { name: spec.model_profile_id })
      : t("organizationDefault");

    const nodes: MapNode[] = [
      {
        key: "surfaces",
        title: t("mapSurfaces"),
        icon: MAP_ICONS.surfaces,
        side: "left",
        // The standing surfaces first - every agent is reachable from the
        // dashboard, the API and the raw socket - then whatever this one was
        // published as: widgets, and each channel binding.
        items: [
          t("surfaceChat"),
          t("surfaceApi"),
          t("surfaceSocket"),
          ...embeds.map((embed) => t("surfaceWidget", { name: embed.name })),
          ...exposures.map(
            (exposure) => `${exposure.channel_bot_name}${exposure.is_active ? "" : " (paused)"}`,
          ),
        ],
        empty: t("chatOnlyNotSlack"),
      },
      {
        key: "model",
        title: t("model"),
        icon: MAP_ICONS.model,
        side: "top",
        items: [profile],
        empty: t("noModel"),
      },
      {
        key: "budget",
        title: t("budget"),
        icon: MAP_ICONS.budget,
        side: "top",
        items: spec.budget?.monthly_usd ? [t("perMonth", { amount: spec.budget.monthly_usd })] : [],
        empty: t("spendsWithoutCeilingIts"),
      },
      {
        key: "capabilities",
        title: t("toolbox"),
        icon: MAP_ICONS.capabilities,
        side: "right",
        items: spec.capabilities
          .filter((binding) => binding.enabled)
          .map((binding) => name(capabilities, binding.id)),
        empty: t("noCapabilitiesEnabled"),
      },
      {
        key: "mcp",
        title: t("mcpServers"),
        icon: MAP_ICONS.mcp,
        side: "right",
        items: spec.mcp_server_ids.map((entry) => name(mcpConnections, entry)),
        empty: t("noMcpServersAttached"),
      },
      {
        key: "knowledge",
        title: t("knowledge"),
        icon: MAP_ICONS.knowledge,
        side: "right",
        items: spec.collection_ids.map((entry) => name(collections, entry)),
        empty: t("noCollectionsAttached"),
      },
      {
        key: "skills",
        title: t("skills"),
        icon: MAP_ICONS.skills,
        side: "right",
        items: spec.skill_ids.map((entry) => name(skills, entry)),
        empty: t("noSkillsAttached"),
      },
    ];

    // The delegation policy, next to the delegates it governs. `allow_dynamic`
    // is the setting with the widest consequences on this page - an agent that
    // may invent specialists mid-run - so the map says it either way.
    const subagentsBinding = spec.capabilities.find((binding) => binding.id === SUBAGENTS_ID);
    if (subagentsBinding?.enabled) {
      const config = readSubagentsConfig(subagentsBinding);
      nodes.push({
        key: "delegation",
        title: tAgents("delegation"),
        icon: MAP_ICONS.delegation,
        side: "bottom",
        items: [
          tAgents("mapHandsBack", { mode: tAgents(MODE_LABEL[config.mode]) }),
          config.allow_dynamic ? t("mapMayInventSpecialists") : t("mapFixedRosterOnly"),
          t("mapDepthLimit", { depth: config.max_depth }),
          t("mapFanoutLimit", { fanout: config.max_fanout }),
        ],
        empty: "",
      });
    }

    return nodes;
  }, [
    spec,
    exposures,
    embeds,
    collections,
    profiles,
    capabilities,
    mcpConnections,
    skills,
    t,
    tAgents,
  ]);

  // Subagents as their own kind of node - another agent this one reaches for,
  // not a tool. A pinned delegate carries a link to its own page and, when the
  // server has walked the tree, its own delegates as children - recursively, so
  // the whole delegation tree reads on one map (#276). An inline specialist has
  // no page and no link. A delegate the organization no longer has, or that
  // this caller cannot see, is named as unreachable rather than dropped - the
  // same silence that hides what publishing will refuse.
  //
  // The first level stays built from the local draft rather than the server
  // tree, because the draft on screen may be ahead of the stored one by an
  // autosave; the server's answer is matched onto it by agent id, which
  // `_one_pin_per_delegate` makes unique on anything publishable.
  const delegateNodes = useMemo<MapDelegate[]>(() => {
    if (!spec) return [];
    const inline = readSubagentsConfig(
      spec.capabilities.find((binding) => binding.id === SUBAGENTS_ID),
    ).inline;
    const walked = new Map(
      (tree?.nodes ?? [])
        .filter((node) => node.kind === "delegate" && node.agent_id !== null)
        .map((node) => [node.agent_id, node] as const),
    );
    // The index is part of the key because a draft can carry a duplicate before
    // publishing refuses it - two pins of one agent, or two specialists sharing
    // a name - and two nodes under one key would collide in the ref map the
    // edges are measured from, dropping one silently. `delegate-list` keys the
    // same way, for the same reason.
    const delegates: MapDelegate[] = (spec.subagents ?? []).map((ref, index) => {
      const agent = agents.find((entry) => entry.id === ref.agent_id);
      const key = `delegate:${ref.agent_id}:${index}`;
      const node = walked.get(ref.agent_id);
      return {
        key,
        // The walk's name first: it is access-checked, and it reaches rows the
        // agent list does not carry. An archived delegate is the one that
        // matters - it is not in the list, so the list alone calls it "an agent
        // you cannot see" while the badge beside it says "Archived".
        name: node?.name ?? agent?.name ?? t("delegateUnreachable"),
        kind: "delegate",
        mode: ref.preferred_mode ?? null,
        href: agent ? ROUTES.AGENT_DETAIL(ref.agent_id) : undefined,
        problem: node && node.status !== "ok" ? node.status : undefined,
        stale: node?.stale || undefined,
        truncated: node?.truncated || undefined,
        children:
          node && node.children.length > 0
            ? toMapDelegates(node.children, tAgents, key)
            : undefined,
      };
    });
    const specialists: MapDelegate[] = inline.map((specialist, index) => ({
      key: `specialist:${index}`,
      name: specialist.name || t("unnamedSpecialist"),
      kind: "specialist",
      mode: specialist.preferred_mode ?? null,
    }));
    return [...delegates, ...specialists];
  }, [spec, agents, tree, t, tAgents]);

  // One line under the delegation heading whenever what is drawn is not the
  // whole tree. The loading half matters as much as the other two: until the
  // walk answers, every first-level delegate renders childless, which is what a
  // leaf looks like - so a map that says nothing is a map claiming a tree it has
  // not read yet.
  const delegationNotice = treeLoading
    ? tAgents("mapTreeLoading")
    : treeError
      ? tAgents("mapTreeUnavailable")
      : tree?.truncated
        ? tAgents("mapTreeTruncated")
        : null;

  // Two capabilities are configured elsewhere and so are kept off this list,
  // because a second control for one field is a control that disagrees with the
  // first. Thinking sits with the model settings: it contributes no tools and
  // changes how the model runs, not what the agent can do. Skills sits in its
  // own section, which owns both halves of a decision that used to be split -
  // see `setSkills`. The workspace stays in the picker: it is a row like the
  // rest, and the detail panel gives it the controls a switch cannot - see
  // `CapabilityWorkbench`.
  const grantable = useMemo(
    () => capabilities.filter((entry) => entry.id !== THINKING_ID && entry.id !== SKILLS_ID),
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
  const setContext = (contextIds: string[]) => update(withContextFiles(spec, contextIds));

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

  /**
   * Store, validate, and then *ask* - publishing is the one click on this page
   * that changes what every channel, widget and API call answers with, and the
   * dialog is where that is said before it happens rather than after.
   */
  async function handlePublish() {
    if (!(await persist())) return;
    const found = await validate();
    setProblems(found);
    if (found.length === 0) setPublishOpen(true);
  }

  // What the next publish will be called. The server owns the number; this
  // predicts it the only way a sentence shown *before* the publish can - one
  // past the newest version, or v1 when there is none.
  const nextVersion = versions.reduce((max, entry) => Math.max(max, entry.version), 0) + 1;

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
                colorSlot={agent.avatar_color}
                size="lg"
                version={avatarVersion}
              />
              {canEdit && (
                <button
                  type="button"
                  onClick={() => avatarInput.current?.click()}
                  disabled={setAvatar.isPending}
                  aria-label={agent.has_avatar ? t("replaceAvatar") : t("uploadAvatar")}
                  title={t("squareImagesLookBest")}
                  className="bg-background/70 text-foreground absolute inset-0 flex items-center justify-center rounded-full opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100 disabled:cursor-not-allowed"
                >
                  <ImagePlus className="h-5 w-5" />
                </button>
              )}
            </span>
            {agent.name}
            <AgentStatusBadge status={agent.status} />
            {/* Two badges, two different questions. This one: is the stored
                draft what published surfaces are answering with - computed
                from the server's copies, so the autosave settling cannot clear
                it into a page that reads as finished while every channel is
                still on the old version (#519). */}
            <PublishState
              agentId={id}
              currentVersionId={agent.current_version_id}
              draftSpec={agent.draft_spec}
            />
            {/* And this one: is my edit stored. The draft saves itself; this
                says where that stands. Quiet when everything is stored -
                "saved" as a permanent label reads as a button. */}
            {canEdit &&
              (saveDraft.isPending ? (
                <Badge variant="secondary">{t("saving")}</Badge>
              ) : (
                isDirty && <Badge variant="secondary">{t("unsaved")}</Badge>
              ))}
          </span>
        }
        description={agent.description ?? undefined}
        breadcrumbs={[{ label: t("agents"), href: ROUTES.AGENTS }, { label: agent.name }]}
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
              title={isPublished ? undefined : t("publishAgentChatWith")}
            >
              <MessageSquare className="h-4 w-4" />
              {t("openChat")}
            </Button>
            {/* Beside the chat button rather than in the overflow menu: the
                map answers "what is this agent" and that question comes up
                before publishing, not after somebody goes looking for it. */}
            <Button variant="outline" onClick={() => setMapOpen(true)}>
              <Network className="h-4 w-4" />
              {t("visualMap")}
            </Button>
            <Button variant="outline" asChild>
              <a href={`/api/agents/${id}/spec.yaml`} download>
                <Download className="h-4 w-4" />
                {t("exportYaml")}
              </a>
            </Button>
            {canPublish && (
              <Button
                onClick={handlePublish}
                disabled={publish.isPending}
                data-tour="agent-publish"
              >
                <Upload className="h-4 w-4" />
                {t("publish")}
              </Button>
            )}
            {canEdit && (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="outline" size="icon" aria-label={t("moreActions")}>
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
                    {t("duplicate")}
                  </DropdownMenuItem>
                  <DropdownMenuItem onSelect={() => avatarInput.current?.click()}>
                    <ImagePlus className="h-4 w-4" />
                    {agent.has_avatar ? t("replaceAvatar2") : t("uploadAvatar2")}
                  </DropdownMenuItem>
                  <DropdownMenuLabel className="text-muted-foreground text-xs font-normal">
                    {t("avatarColour")}
                  </DropdownMenuLabel>
                  {/* Not menu items: a swatch click picks a colour and leaves the
                      menu open, where selecting an item would close it. */}
                  <div className="px-2 pb-1.5">
                    <AvatarColorPicker
                      value={agent.avatar_color ?? null}
                      onChange={(slot) => setColor.mutate(slot)}
                      disabled={setColor.isPending}
                    />
                  </div>
                  <DropdownMenuSeparator />
                  {agent.status === "archived" ? (
                    <DropdownMenuItem onSelect={() => unarchive.mutate(id)}>
                      <ArchiveRestore className="h-4 w-4" />
                      {t("restore")}
                    </DropdownMenuItem>
                  ) : (
                    <DropdownMenuItem onSelect={() => setConfirming("archive")}>
                      <Archive className="h-4 w-4" />
                      {t("archive")}
                    </DropdownMenuItem>
                  )}
                  <DropdownMenuSeparator />
                  <DropdownMenuItem
                    className="text-destructive focus:text-destructive"
                    onSelect={() => setConfirming("delete")}
                  >
                    <Trash2 className="h-4 w-4" />
                    {t("deletePermanently")}
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
            <DialogTitle>{t("visualMap")}</DialogTitle>
            <DialogDescription>{t("draftAsStandsWhat")}</DialogDescription>
          </DialogHeader>
          {spec && (
            <AgentMap
              agentName={spec.name}
              instructions={spec.instructions}
              nodes={mapNodes}
              delegates={delegateNodes}
              delegationNotice={delegationNotice}
            />
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
            <DialogTitle>{t("connectMcpServer")}</DialogTitle>
            <DialogDescription>{t("connectServerOrganizationBecomes")}</DialogDescription>
          </DialogHeader>
          <McpServerList canManageOrganization={can(Perm.connectionsManage)} />
        </DialogContent>
      </Dialog>

      <PublishDialog
        open={publishOpen}
        onOpenChange={setPublishOpen}
        version={nextVersion}
        environments={environments}
        publishing={publish.isPending}
        onConfirm={async () => {
          try {
            await publish.mutateAsync(null);
            setPublishOpen(false);
          } catch {
            // The hook already toasts the refusal; the dialog stays open so
            // the retry is one click rather than a re-run of validation.
          }
        }}
      />

      {confirming === "archive" && (
        <ConfirmDialog
          open
          onOpenChange={() => setConfirming(null)}
          title={tc("archiveNamedConfirm", { name: agent.name })}
          description={t("stopsAnsweringEverywhereAvailable")}
          confirmLabel={t("archive")}
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
          title={tc("deleteNamedConfirm", { name: agent.name })}
          description={t("removesAgentEveryVersion")}
          confirmLabel={t("delete")}
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
              {t("agentCannotBePublished")}
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
          <TabsTrigger value="build" data-tour="agent-tab-build">
            {t("build")}
          </TabsTrigger>
          <TabsTrigger value="toolbox" data-tour="agent-tab-toolbox">
            {t("toolbox")}
          </TabsTrigger>
          <TabsTrigger value="knowledge" data-tour="agent-tab-knowledge">
            {t("knowledge")}
          </TabsTrigger>
          <TabsTrigger value="skills" data-tour="agent-tab-skills">
            {t("skills")}
          </TabsTrigger>
          <TabsTrigger value="limits" data-tour="agent-tab-limits">
            {t("limits")}
          </TabsTrigger>
          <TabsTrigger value="availability" data-tour="agent-tab-availability">
            {t("availability")}
          </TabsTrigger>
          <TabsTrigger value="history" data-tour="agent-tab-history">
            {t("history")}
          </TabsTrigger>
        </TabsList>

        <TabsContent value="build" className="mt-4 space-y-6">
          <Card data-tour="agent-instructions">
            <CardHeader>
              <CardTitle>{t("instructions")}</CardTitle>
              <CardDescription>{t("agentAposSBehaviour")}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <MarkdownEditor
                // Named, because a placeholder is not a label: it is the only
                // accessible name this control had, and it is the one thing that
                // disappears the moment somebody types into it.
                label={t("instructions2")}
                value={spec.instructions}
                onChange={(instructions) => update({ instructions })}
                rows={10}
                disabled={!canEdit}
                placeholder={t("youAreSupportCopilot")}
              />
              <div className="space-y-2" data-tour="agent-model-picker">
                <Label>{t("model")}</Label>
                <ModelProfilePicker
                  // A model profile is `connections:manage`, which somebody who
                  // may edit this agent need not hold - and both halves of this
                  // panel write one: the form posts `/providers/model-profiles`
                  // and the bin deletes one from under every agent pointed at
                  // it. Ungated, they were a 403 dressed as a control, the same
                  // way Connect server below would be without its own gate.
                  allowAdd={can(Perm.connectionsManage)}
                  // The Builder is where an organization's models are managed,
                  // so it is the one panel that also takes one away.
                  allowRemove={can(Perm.connectionsManage)}
                  profiles={profiles}
                  profilesStatus={profilesStatus}
                  value={spec.model_profile_id ?? null}
                  onChange={(model_profile_id) => update({ model_profile_id })}
                  disabled={!canEdit}
                />
                {/* Said where the missing control would be, because publish
                    would otherwise be the first thing to say it. */}
                {modelDeadEnd && (
                  <p className="text-muted-foreground text-xs">{t("noModelNeedsConnections")}</p>
                )}
              </div>
            </CardContent>
          </Card>

          <Card data-tour="agent-model">
            <CardHeader>
              <CardTitle>{t("modelSettings")}</CardTitle>
              <CardDescription>{t("howAgentAsksIts")}</CardDescription>
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
          <Card data-tour="agent-capabilities">
            <CardHeader>
              <CardTitle>{t("capabilities")}</CardTitle>
              <CardDescription>{t("whatAgentCanDo")}</CardDescription>
            </CardHeader>
            <CardContent>
              <CapabilityWorkbench
                catalog={grantable}
                selected={spec.capabilities}
                onToggle={toggleCapability}
                onChange={updateCapability}
                // Delegates are top level on the spec rather than inside the
                // delegation capability's config, so the panel that edits them
                // is handed that slice as well as the binding.
                subagents={spec.subagents ?? []}
                onSubagentsChange={(subagents) => update({ subagents })}
                // So promoting a specialist that runs on the parent's model can
                // resolve one for the standalone agent it becomes.
                modelProfileId={spec.model_profile_id ?? null}
                disabled={!canEdit}
              />
            </CardContent>
          </Card>

          <Card data-tour="agent-mcp">
            {/* The passive tour points here rather than at the card: the picker
                below embeds the whole server catalog, so the card runs well past
                the bottom of the screen and a spotlight on it lit the entire
                viewport — a highlight that highlights nothing, with the caption
                stranded in the one dim strip left (#624). The card keeps its own
                anchor for the guided flow, which needs the list itself reachable
                so the reader can tick a server. */}
            <CardHeader data-tour="agent-mcp-intro">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0 space-y-1.5">
                  <CardTitle>{t("mcpServers")}</CardTitle>
                  <CardDescription>
                    {t.rich("mcpServersDescription", {
                      servers: (chunks) => (
                        <Link href={ROUTES.MCP_SERVERS} className="underline">
                          {chunks}
                        </Link>
                      ),
                    })}
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
                  <Button
                    variant="outline"
                    size="sm"
                    data-tour="agent-mcp-connect"
                    onClick={() => setConnectingMcp(true)}
                  >
                    <Plug className="h-3.5 w-3.5" />
                    {t("connectServer")}
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
              <p className="text-muted-foreground mt-4 text-xs">{t("twoLimitsWorthKnowing")}</p>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="knowledge" className="mt-4 space-y-6">
          <Card data-tour="agent-collections">
            <CardHeader>
              <CardTitle>{t("collections")}</CardTitle>
              <CardDescription>{t("whatAgentMaySearch")}</CardDescription>
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
          <Card data-tour="agent-skills">
            <CardHeader>
              <CardTitle>{t("skills2")}</CardTitle>
              <CardDescription>{t("writtenKnowHowAgent")}</CardDescription>
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

          {/* Standing context, beside skills because both are things the agent
              reads rather than searches - a glossary or a policy injected into
              the prompt or read on demand, not a procedure loaded on decision. */}
          <Card>
            <CardHeader>
              <CardTitle>{t("context")}</CardTitle>
              <CardDescription>{t("standingContextAgent")}</CardDescription>
            </CardHeader>
            <CardContent>
              <ContextGallery
                files={contextFiles}
                total={contextCount}
                selectedIds={spec.context_ids}
                onToggle={(fileId) => setContext(toggleId(spec.context_ids, fileId))}
                disabled={!canEdit}
              />
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="limits" className="mt-4 space-y-6">
          <Card data-tour="agent-limits">
            <CardHeader>
              <CardTitle>{t("runLimits")}</CardTitle>
              <CardDescription>{t("agentAposSOwn")}</CardDescription>
            </CardHeader>
            <CardContent className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="monthly">{t("monthlyUsd")}</Label>
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
                  placeholder={t("noLimit")}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="max-steps">{t("maxStepsPerRun")}</Label>
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
                  placeholder={t("n100Default")}
                />
                <p className="text-muted-foreground text-xs">{t("howManyModelRequests")}</p>
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
          <div data-tour="agent-availability">
            <ExposuresPanel
              agentId={id}
              canManage={canPublish}
              hasWorkspace={spec.capabilities.some(
                (binding) => binding.id === SANDBOX_ID && binding.enabled !== false,
              )}
            />
          </div>
          <EmbedsPanel agentId={id} canManage={canPublish} />
          <SharingPanel resourceType="agent" resourceId={id} canManage={canEdit} />
        </TabsContent>

        <TabsContent value="history" className="mt-4 space-y-6">
          <Card data-tour="agent-history">
            <CardHeader>
              <CardTitle>{t("environments")}</CardTitle>
              <CardDescription>{t("namedPointersAtPublished")}</CardDescription>
            </CardHeader>
            <CardContent>
              <EnvironmentsPanel agentId={id} canManage={canPublish} />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <History className="h-4 w-4" />
                {t("versions")}
              </CardTitle>
              <CardDescription>{t("eachPublishFreezesSpec")}</CardDescription>
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
              <CardTitle>{t("recentRuns")}</CardTitle>
              <CardDescription>{t("whetherAgentWorkingWhat")}</CardDescription>
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
  const t = useTranslations("pages.agents");
  return (
    <div role="status" aria-label={t("loading")} className="space-y-6">
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
