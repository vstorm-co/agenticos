"use client";

import {
  AudiencePicker,
  EVERYONE,
  audiencePayload,
  type Audience,
} from "@/components/sharing/audience-picker";
import { useState } from "react";
import { ChevronRight } from "lucide-react";
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
  Textarea,
} from "@/components/ui";
import { useAgents } from "@/hooks";
import { submitFailure } from "@/lib/api-error";
import type { Agent } from "@/types/agents";
import { useTranslations } from "next-intl";
import { DIALOG_BODY, DIALOG_COLUMN, DIALOG_FORM } from "@/lib/dialog-sizes";
import { cn } from "@/lib/utils";
import { MAX_AGENT_CATEGORIES, MAX_AGENT_TAGS } from "@/lib/agent-labels";
import { ASK_USER_ID, unboundBinding } from "@/lib/agent-spec";

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
 * The handle is on screen while the name is being typed because it is the part
 * that cannot be changed afterwards and the part a duplicate is refused on. A
 * reader who has seen `@support` under the field can act on "that handle is
 * taken"; one who has not is being told about a value they never entered.
 */
export function CreateAgentDialog({ open, onOpenChange, onCreated }: CreateAgentDialogProps) {
  const tErrors = useTranslations("errors");
  const t = useTranslations("agents");
  const tAgents = useTranslations("pages.agents");
  const [moreOpen, setMoreOpen] = useState(false);
  const { create } = useAgents();
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
      const agent = await create.mutateAsync({
        spec: {
          name,
          description: description || null,
          instructions: "",
          model_profile_id: null,
          model_settings: {},
          // Every new agent can ask the person a question rather than guess
          // (#2064); its author can switch it off in the Builder.
          capabilities: [{ ...unboundBinding(ASK_USER_ID), enabled: true }],
          collection_ids: [],
          skill_ids: [],
          context_ids: [],
          mcp_servers: [],
          budget: null,
        },
        ...audiencePayload(audience),
        categories,
        tags,
      });
      setName("");
      setDescription("");
      setAudience(EVERYONE);
      setCategories([]);
      setTags([]);
      setErrors({});
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

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      {/* A shape as well as a width. The form grew a visibility, two chip
          editors and a preview that gets taller with every tag, which on a phone
          or a short window pushed the header and the Create button off the
          screen with nothing to scroll - a dialog you cannot submit. */}
      <DialogContent className={cn(DIALOG_FORM, DIALOG_COLUMN)}>
        <DialogHeader>
          <DialogTitle>{t("newAgent")}</DialogTitle>
          <DialogDescription>{t("startsAsDraftNothing")}</DialogDescription>
        </DialogHeader>
        {/* `min-h-0` because a flex child refuses to shrink without it, which is
            how the body grows past the dialog's own ceiling instead of scrolling
            inside it. The side padding keeps a focus ring off the scroller's
            edge, where it would be sliced. */}
        <div className={cn(DIALOG_BODY, "space-y-4")}>
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
          <div>
            <button
              type="button"
              aria-expanded={moreOpen}
              onClick={() => setMoreOpen((open) => !open)}
              className="text-muted-foreground hover:text-foreground flex items-center gap-1.5 text-sm font-medium transition-colors"
            >
              <ChevronRight
                className={cn("h-4 w-4 transition-transform", moreOpen && "rotate-90")}
                aria-hidden
              />
              {t("moreOptions")}
            </button>
            {moreOpen && (
              <div className="mt-3 space-y-4">
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
                      maxItems={MAX_AGENT_TAGS}
                      maxLength={MAX_LABEL}
                    />
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("cancel2")}
          </Button>
          <Button onClick={handleCreate} disabled={!name.trim() || create.isPending}>
            {t("create")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
