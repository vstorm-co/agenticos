"use client";

import { useState } from "react";
import { ChevronRight } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useQuery } from "@tanstack/react-query";
import { IngestionSettings } from "@/components/kb/ingestion-settings";
import { InlineSecret } from "@/components/vault/inline-secret";
import { ProviderRow } from "@/components/vault/provider-row";
import { useKnowledgeBases, useSecrets } from "@/hooks";
import { apiClient } from "@/lib/api-client";
import { submitFailure } from "@/lib/api-error";
import {
  DEFAULT_INGESTION_CONFIG,
  INGESTION_FORM_FIELDS,
  ingestionProblems,
  sameIngestion,
} from "@/lib/ingestion-config";
import type { CreateKnowledgeBaseInput, IngestionConfig, KBScope } from "@/types";
import { useTranslations } from "next-intl";

/** What the backend accepts, so an over-long value is refused before it is sent. */
const MAX_NAME = 128;
const MAX_DESCRIPTION = 500;

/** Purposes whose keys can pay for embeddings - mirrors the backend's list. */
const EMBEDDING_KEY_PURPOSE = "openrouter";

/** Sentinel for "the deployment's key" - a Select item may not be empty. */
const DEPLOYMENT_KEY = "__deployment__";

interface EmbeddingModels {
  default: string;
  models: { model: string; dim: number }[];
}

interface CreateKBDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated?: (id: string) => void;
}

export function CreateKBDialog({ open, onOpenChange, onCreated }: CreateKBDialogProps) {
  const t = useTranslations("kb");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [scope, setScope] = useState<KBScope>("personal");
  const [ingestion, setIngestion] = useState<IngestionConfig>(DEFAULT_INGESTION_CONFIG);
  const [embeddingModel, setEmbeddingModel] = useState<string | null>(null);
  const [embeddingSecretId, setEmbeddingSecretId] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errors, setErrors] = useState<Readonly<Record<string, string>>>({});
  const { createKB } = useKnowledgeBases();
  const { secrets } = useSecrets();
  const embeddingKeys = secrets.filter((secret) => secret.purpose === EMBEDDING_KEY_PURPOSE);
  // Which models this build can index with. A build property, not tenant data,
  // so it never goes stale while a dialog is open.
  const { data: embeddingModels } = useQuery({
    queryKey: ["rag", "embedding-models"],
    queryFn: () => apiClient.get<EmbeddingModels>("/rag/embedding-models"),
    staleTime: Infinity,
  });

  // Nobody has chosen an ingestion configuration until it differs from what is
  // shown, and sending one they did not choose is not a harmless default: the
  // API fills a *missing* object from this deployment's settings, which an
  // operator may have set to something other than the platform's. Posting the
  // form's starting values would quietly overrule that.
  const chosen = !sameIngestion(ingestion, DEFAULT_INGESTION_CONFIG);
  const localProblems = chosen ? ingestionProblems(ingestion) : {};
  const canSubmit = name.trim().length > 0 && Object.keys(localProblems).length === 0;

  const reset = () => {
    setName("");
    setDescription("");
    setScope("personal");
    setIngestion(DEFAULT_INGESTION_CONFIG);
    setEmbeddingModel(null);
    setEmbeddingSecretId(null);
    setErrors({});
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;
    setIsSubmitting(true);
    try {
      const input: CreateKnowledgeBaseInput = {
        name: name.trim(),
        description: description.trim() || undefined,
        scope,
      };
      // The key is absent rather than undefined: "inherit the deployment's
      // defaults" is a thing the API is told by being told nothing.
      if (chosen) input.ingestion_config = ingestion;
      if (embeddingModel && embeddingModel !== embeddingModels?.default) {
        input.embedding_model = embeddingModel;
      }
      if (embeddingSecretId) input.embedding_secret_id = embeddingSecretId;
      const kb = await createKB(input);
      reset();
      onOpenChange(false);
      onCreated?.(kb.id);
    } catch (error) {
      // No `identifiedBy`: collection names are deliberately not unique - each
      // one gets its own physical collection - so nothing here can come back as
      // a conflict, and claiming a conflict was about the name would be a guess.
      //
      // A refusal about the image model names a profile rather than a field, so
      // it arrives as the toast below carrying the server's own sentence. The
      // picker inside the images section says the same thing earlier, by badging
      // a profile that has no key.
      const failure = submitFailure(error, {
        fields: ["name", "description", ...INGESTION_FORM_FIELDS],
      });
      setErrors(failure.fields);
      if (failure.toast) toast.error(failure.toast);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      {/* A column with one scrolling part, so expanding the settings never
          pushes Create off the bottom of the screen. */}
      <DialogContent className="flex max-h-[85vh] flex-col sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t("createKnowledgeBase")}</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="flex min-h-0 flex-1 flex-col gap-4">
          <div className="-mx-1 min-h-0 flex-1 space-y-4 overflow-y-auto px-1">
            <FormField label={t("name")} htmlFor="kb-name" error={errors.name}>
              <Input
                id="kb-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder={t("productDocs")}
                maxLength={MAX_NAME}
                autoFocus
              />
            </FormField>
            <FormField
              label={t("descriptionOptional")}
              htmlFor="kb-description"
              error={errors.description}
            >
              <Textarea
                id="kb-description"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder={t("whatDocumentsWillKb")}
                maxLength={MAX_DESCRIPTION}
                rows={2}
              />
            </FormField>
            <div className="space-y-1.5">
              <Label htmlFor="kb-scope">{t("scope")}</Label>
              <Select value={scope} onValueChange={(v) => setScope(v as KBScope)}>
                <SelectTrigger id="kb-scope">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="personal">{t("personalOnlyYou")}</SelectItem>
                  <SelectItem value="org">{t("organizationAllMembers")}</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {/*
              Folded away like the parsing section: the choice is frozen at
              creation (the vector column is created at the model's width), so
              it matters - but the default is right for almost everyone.
            */}
            <details className="group border-border rounded-lg border">
              <summary className="text-foreground flex cursor-pointer list-none items-center gap-1.5 p-3 text-sm">
                <ChevronRight className="h-3.5 w-3.5 transition-transform group-open:rotate-90" />
                {t("embeddings")}
                <span className="text-muted-foreground ml-auto text-xs">
                  {embeddingModel && embeddingModel !== embeddingModels?.default
                    ? embeddingModel
                    : t("deploymentDefault")}
                </span>
              </summary>
              <div className="space-y-4 border-t p-4">
                <p className="text-muted-foreground text-xs">{t("frozenAtCreationCollection")}</p>
                <div className="space-y-1.5">
                  <Label htmlFor="kb-embedding-model">{t("model")}</Label>
                  <Select
                    value={embeddingModel ?? embeddingModels?.default ?? ""}
                    onValueChange={setEmbeddingModel}
                    disabled={!embeddingModels}
                  >
                    <SelectTrigger id="kb-embedding-model">
                      <SelectValue placeholder={t("loadingModels")} />
                    </SelectTrigger>
                    <SelectContent>
                      {(embeddingModels?.models ?? []).map((entry) => (
                        <SelectItem
                          key={entry.model}
                          value={entry.model}
                          // In the list rather than in the row: the trigger
                          // draws whatever the row draws, and "deployment
                          // default" is a comparison against the other options.
                          trailing={
                            entry.model === embeddingModels?.default && (
                              <span className="text-muted-foreground ml-auto shrink-0 pl-2 text-xs">
                                {t("deploymentDefault")}
                              </span>
                            )
                          }
                        >
                          {/* Whichever model is chosen, the request goes to
                              OpenRouter and an OpenRouter key pays for it - so
                              the mark says which key that is, which a bare
                              model id never did. */}
                          <ProviderRow provider={EMBEDDING_KEY_PURPOSE} name={entry.model} />
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="kb-embedding-key">{t("key")}</Label>
                  <Select
                    value={embeddingSecretId ?? DEPLOYMENT_KEY}
                    onValueChange={(v) => setEmbeddingSecretId(v === DEPLOYMENT_KEY ? null : v)}
                  >
                    <SelectTrigger id="kb-embedding-key">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {/* The deployment's own key is an OpenRouter key too -
                          `EmbeddingService` sends every request to
                          openrouter.ai - so it carries the same mark as the
                          organization's, and the row says which of them pays. */}
                      <SelectItem value={DEPLOYMENT_KEY}>
                        <ProviderRow provider={EMBEDDING_KEY_PURPOSE} name={t("deploymentKey")} />
                      </SelectItem>
                      {embeddingKeys.map((secret) => (
                        <SelectItem key={secret.id} value={secret.id}>
                          <ProviderRow
                            provider={EMBEDDING_KEY_PURPOSE}
                            name={secret.name}
                            hint={secret.hint}
                          />
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <p className="text-muted-foreground text-xs">{t("keyHereBillsEmbeddings")}</p>
                  {/* Rather than only telling somebody to go and add one: a picker
                      with nothing in it and no way to fill it is a dead end, and
                      the answer to "add a key in the vault" is a form, not a
                      sentence. */}
                  <InlineSecret
                    kind="api_key"
                    purpose={EMBEDDING_KEY_PURPOSE}
                    suggestedName={t("embeddingsKeyName")}
                    onCreated={setEmbeddingSecretId}
                  />
                </div>
              </div>
            </details>

            {/*
              Folded away, because creating a collection is a two-field job and
              most people will never open this. It is a disclosure rather than a
              step in a wizard for the same reason: a wizard would make everybody
              walk past parser options to reach a button they could already press.
            */}
            <details className="group border-border rounded-lg border">
              <summary className="text-foreground flex cursor-pointer list-none items-center gap-1.5 p-3 text-sm">
                <ChevronRight className="h-3.5 w-3.5 transition-transform group-open:rotate-90" />
                {t("howDocumentsAreParsed")}
                <span className="text-muted-foreground ml-auto text-xs">
                  {chosen ? t("customized") : t("deploymentDefaults")}
                </span>
              </summary>
              <div className="space-y-4 border-t p-4">
                <p className="text-muted-foreground text-xs">{t("leftAloneCollectionInherits")}</p>
                <IngestionSettings
                  idPrefix="kb-new"
                  value={ingestion}
                  onChange={setIngestion}
                  errors={{ ...localProblems, ...errors }}
                  disabled={isSubmitting}
                />
              </div>
            </details>
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {t("cancel")}
            </Button>
            <Button type="submit" disabled={!canSubmit || isSubmitting}>
              {isSubmitting ? t("creating") : t("create")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
