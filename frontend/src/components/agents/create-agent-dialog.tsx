"use client";

import {
  AudiencePicker,
  EVERYONE,
  audiencePayload,
  type Audience,
} from "@/components/sharing/audience-picker";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { ChipsInput } from "@/components/agents/chips-input";
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  FormField,
  Input,
  Label,
  MoreOptions,
  Textarea,
} from "@/components/ui";
import { useAgents, useCapabilityCatalog } from "@/hooks";
import { useCreateSystemAgent } from "@/hooks/use-agents";
import { submitFailure } from "@/lib/api-error";
import type { Agent, SystemAgentKind } from "@/types/agents";
import { useTranslations } from "next-intl";
import { DIALOG_BODY, DIALOG_COLUMN, DIALOG_FORM } from "@/lib/dialog-sizes";
import { cn } from "@/lib/utils";
import { MAX_AGENT_CATEGORIES, MAX_AGENT_TAGS } from "@/lib/agent-labels";
import { DescribeWithArchitect } from "@/components/authoring/describe-with-architect";
import { SystemAgentKinds } from "@/components/agents/system-agent-kinds";

/** What the backend will accept, so a longer name is refused before it is sent. */
const MAX_NAME = 128;
const MAX_DESCRIPTION = 1000;
/** The longest label the server stores, so a longer chip is refused before it is sent. */
const MAX_LABEL = 32;

/**
 * The handle an agent will be addressed by, derived from its name.
 *
 * A mirror of `slugify` in `backend/app/services/agent_registry.py`, fallback
 * included: a name with nothing slug-able in it really does become `agent`
 * there. Mirroring it exactly is the point - this is shown as a prediction, and
 * a prediction that quietly disagrees with the server is worse than none. The
 * server remains the authority; it derives the handle again on create and its
 * answer is the one that is stored.
 */
export function deriveHandle(name: string): string {
  const slug = name
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9-]+/g, "-")
    .replace(/-{2,}/g, "-")
    .replace(/^-+|-+$/g, "");
  return slug.slice(0, 64) || "agent";
}

interface CreateAgentDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (agent: Agent) => void;
}

/**
 * New agent: a name, a description, and the handle the name will produce.
 *
 * Or a system agent of the organization's own - picked where it runs - made from its
 * kind's definition, which asks only for a name.
 *
 * The handle is on screen while the name is being typed because it is the part
 * that cannot be changed afterwards and the part a duplicate is refused on. A
 * reader who has seen `@support` under the field can act on "that handle is
 * taken"; one who has not is being told about a value they never entered.
 */
export function CreateAgentDialog({ open, onOpenChange, onCreated }: CreateAgentDialogProps) {
  const tErrors = useTranslations("errors");
  const t = useTranslations("agents");
  const tAgents = useTranslations("pages.agents");
  const { create, categoryOptions, tagOptions } = useAgents();
  const createSystem = useCreateSystemAgent();
  const [making, setMaking] = useState<"agent" | "system">("agent");
  const [kind, setKind] = useState<SystemAgentKind>("judge");
  // A new agent starts with what the starter agent has - the Claude Code like
  // template - so it can ask, plan, search, work in a sandbox and delegate from
  // its first run; its author switches off what it should not do.
  const {
    capabilities: catalog,
    isFetching: catalogFetching,
    refetch: refetchCatalog,
  } = useCapabilityCatalog();
  // Asked again on every open: whether the organization can run a container
  // workspace changes while the page stays open, and the dialog stays mounted.
  useEffect(() => {
    if (open) void refetchCatalog({ cancelRefetch: false });
  }, [open, refetchCatalog]);
  const starter = catalog.flatMap((entry) =>
    entry.recommended ? [{ ...entry.recommended, enabled: true }] : [],
  );
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  // Organization by default. An agent is a thing a company builds, and one
  // nobody else can find is the exception - it used to be the rule, so every
  // agent was made invisible and then shared by hand.
  const [audience, setAudience] = useState<Audience>(EVERYONE);
  const [categories, setCategories] = useState<string[]>([]);
  const [tags, setTags] = useState<string[]>([]);
  const [errors, setErrors] = useState<Readonly<Record<string, string>>>({});

  function edit(field: "name" | "description", value: string) {
    if (field === "name") setName(value);
    else setDescription(value);
    // The server's verdict was about the value that was sent. Keeping it on
    // screen while the reader changes that value is how a form ends up marking
    // a name that is now perfectly good.
    if (errors[field]) setErrors(({ [field]: _removed, ...rest }) => rest);
  }

  async function handleCreate() {
    try {
      const agent =
        making === "system" ? await createSystem.mutateAsync({ kind, name }) : await createAgent();
      setName("");
      setDescription("");
      setAudience(EVERYONE);
      setCategories([]);
      setTags([]);
      setErrors({});
      setMaking("agent");
      setKind("judge");
      onOpenChange(false);
      onCreated(agent);
    } catch (error) {
      // The dialog stays open with everything still in it: the usual reason to
      // be here is a handle that is taken, which is one word away from working.
      const failure = submitFailure(
        error,
        {
          fields: ["name", "description"],
          identifiedBy: "name",
        },
        tErrors,
      );
      setErrors(failure.fields);
      if (failure.toast) toast.error(failure.toast);
    }
  }

  function createAgent() {
    return create.mutateAsync({
      spec: {
        name,
        description: description || null,
        instructions: "",
        model_profile_id: null,
        model_settings: {},
        capabilities: starter,
        collection_ids: [],
        skill_ids: [],
        context_ids: [],
        mcp_servers: [],
        budget: null,
      },
      ...audiencePayload(audience),
      categories,
      tags,
      from_starter: true,
    });
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      {/* A shape as well as a width. The form grew a visibility, two chip
          editors and a preview that gets taller with every tag, which on a phone
          or a short window pushed the header and the Create button off the
          screen with nothing to scroll - a dialog you cannot submit. */}
      <DialogContent className={cn(DIALOG_FORM, DIALOG_COLUMN)}>
        <DialogHeader>
          <DialogTitle>{t("newAgent")}</DialogTitle>
          <DialogDescription>
            {making === "system" ? t("systemStartsAs") : t("startsAsDraftNothing")}
          </DialogDescription>
        </DialogHeader>
        {/* `min-h-0` because a flex child refuses to shrink without it, which is
            how the body grows past the dialog's own ceiling instead of scrolling
            inside it. The side padding keeps a focus ring off the scroller's
            edge, where it would be sliced. */}
        <div className={cn(DIALOG_BODY, "space-y-4")}>
          <div role="radiogroup" aria-label={t("newKindLabel")} className="grid grid-cols-2 gap-2">
            {(["agent", "system"] as const).map((option) => (
              <Button
                key={option}
                type="button"
                role="radio"
                aria-checked={making === option}
                variant={making === option ? "default" : "outline"}
                onClick={() => setMaking(option)}
              >
                {option === "agent" ? t("newKindAgent") : t("newKindSystem")}
              </Button>
            ))}
          </div>
          {making === "system" ? (
            <>
              <SystemAgentKinds value={kind} onChange={setKind} />
              <FormField
                label={t("name4")}
                htmlFor="system-agent-name"
                error={errors.name}
                description={t("systemRunsOn")}
              >
                <Input
                  value={name}
                  onChange={(event) => edit("name", event.target.value)}
                  placeholder={t("systemNamePlaceholder")}
                  maxLength={MAX_NAME}
                />
              </FormField>
            </>
          ) : (
            <>
              <DescribeWithArchitect onAsked={() => onOpenChange(false)} />
              <FormField
                label={t("name4")}
                htmlFor="agent-name"
                error={errors.name}
                description={
                  <>
                    {t.rich("handleDescription", {
                      handle: deriveHandle(name || t("handlePlaceholder")),
                      at: (chunks) => <span className="font-mono">@{chunks}</span>,
                    })}
                  </>
                }
              >
                <Input
                  value={name}
                  onChange={(event) => edit("name", event.target.value)}
                  placeholder={t("supportCopilot")}
                  maxLength={MAX_NAME}
                />
              </FormField>
              <div className="space-y-1.5">
                <Label>{t("whoCanFindIt")}</Label>
                <AudiencePicker value={audience} onChange={setAudience} />
              </div>

              {/* Optional, and folded: a draft needs a name and an audience, and the
              catalog details can wait for the detail page - which changes them
              later without a publish. */}
              <MoreOptions label={t("moreOptions")}>
                <FormField
                  label={t("description")}
                  htmlFor="agent-description"
                  error={errors.description}
                >
                  <Textarea
                    value={description}
                    onChange={(event) => edit("description", event.target.value)}
                    placeholder={t("answersCustomerQuestionsFrom")}
                    maxLength={MAX_DESCRIPTION}
                    rows={2}
                  />
                </FormField>
                {/* Side by side: two halves of one question. */}
                <div className="grid gap-4 sm:grid-cols-2">
                  <div className="space-y-1.5">
                    <Label>{tAgents("categories")}</Label>
                    <ChipsInput
                      values={categories}
                      onChange={setCategories}
                      inputLabel={tAgents("addCategory")}
                      removeLabel={(value) => tAgents("removeCategory", { value })}
                      placeholder={tAgents("addCategoryPlaceholder")}
                      suggestions={categoryOptions}
                      suggestionsLabel={tAgents("inCategoryUse")}
                      maxItems={MAX_AGENT_CATEGORIES}
                      maxLength={MAX_LABEL}
                    />
                  </div>
                  <div className="space-y-1.5">
                    <Label>{tAgents("tags")}</Label>
                    <ChipsInput
                      values={tags}
                      onChange={setTags}
                      inputLabel={tAgents("addTag")}
                      removeLabel={(value) => tAgents("removeTag", { value })}
                      placeholder={tAgents("addTagPlaceholder")}
                      suggestions={tagOptions}
                      suggestionsLabel={tAgents("inTagUse")}
                      maxItems={MAX_AGENT_TAGS}
                      maxLength={MAX_LABEL}
                    />
                  </div>
                </div>
              </MoreOptions>
            </>
          )}
        </div>
        <DialogFooter className="items-center">
          <p className="text-muted-foreground mr-auto hidden text-xs sm:block">
            {making === "agent" && t("startsWithRecommended", { count: starter.length })}
          </p>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("cancel2")}
          </Button>
          <Button
            onClick={handleCreate}
            loading={create.isPending || createSystem.isPending}
            disabled={!name.trim() || (making === "agent" && catalogFetching)}
          >
            {t("create")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
