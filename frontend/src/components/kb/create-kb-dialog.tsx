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
import { EmbeddingProviderFields, useEmbeddingProviders } from "@/components/kb/embedding-picker";
import { IngestionSettings } from "@/components/kb/ingestion-settings";
import { InlineSecret } from "@/components/vault/inline-secret";
import { ProviderRow } from "@/components/vault/provider-row";
import { useKnowledgeBases } from "@/hooks";
import { useSecrets } from "@/hooks/use-secrets";
import { submitFailure } from "@/lib/api-error";
import {
  DEFAULT_INGESTION_CONFIG,
  INGESTION_FORM_FIELDS,
  ingestionProblems,
  sameIngestion,
} from "@/lib/ingestion-config";
import { DEFAULT_RERANK_MODEL, RERANK_KEY_PURPOSE, RERANK_OFF } from "@/lib/rerank-config";
import { cn } from "@/lib/utils";
import type { CreateKnowledgeBaseInput, IngestionConfig, KBScope } from "@/types";
import { useTranslations } from "next-intl";
import { DIALOG_COLUMN, DIALOG_WIDE } from "@/lib/dialog-sizes";

/** What the backend accepts, so an over-long value is refused before it is sent. */
const MAX_NAME = 128;
const MAX_DESCRIPTION = 500;

interface CreateKBDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated?: (id: string) => void;
}

export function CreateKBDialog({ open, onOpenChange, onCreated }: CreateKBDialogProps) {
  const tErrors = useTranslations("errors");
  const t = useTranslations("kb");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [scope, setScope] = useState<KBScope>("personal");
  const [ingestion, setIngestion] = useState<IngestionConfig>(DEFAULT_INGESTION_CONFIG);
  const [embeddingModel, setEmbeddingModel] = useState<string | null>(null);
  const [embeddingProvider, setEmbeddingProvider] = useState<string | null>(null);
  const [embeddingSecretId, setEmbeddingSecretId] = useState<string | null>(null);
  const [rerankSecretId, setRerankSecretId] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errors, setErrors] = useState<Readonly<Record<string, string>>>({});
  const { createKB } = useKnowledgeBases();
  const { secrets } = useSecrets();
  const rerankKeys = secrets.filter((secret) => secret.purpose === RERANK_KEY_PURPOSE);
  const { models: embeddingModels, unreadable: modelsUnreadable } = useEmbeddingProviders();
  // Whose endpoint the models on offer belong to. The provider decides both the
  // model list and which vault keys can pay, so it is resolved before either -
  // and a model the chosen provider does not serve is not a model this
  // collection can be created with.
  const provider = embeddingProvider ?? embeddingModels?.default_provider ?? "";
  const providerEntry = embeddingModels?.providers.find((item) => item.provider === provider);
  const offered = providerEntry?.models ?? [];
  const defaultModel =
    offered.find((entry) => entry.model === embeddingModels?.default)?.model ??
    offered[0]?.model ??
    "";
  const model = offered.some((entry) => entry.model === embeddingModel)
    ? (embeddingModel ?? defaultModel)
    : defaultModel;

  // Nobody has chosen an ingestion configuration until it differs from what is
  // shown, and sending one they did not choose is not a harmless default: the
  // API fills a *missing* object from this deployment's settings, which an
  // operator may have set to something other than the platform's. Posting the
  // form's starting values would quietly overrule that.
  const chosen = !sameIngestion(ingestion, DEFAULT_INGESTION_CONFIG);
  const localProblems = chosen ? ingestionProblems(ingestion, t) : {};
  const canSubmit = name.trim().length > 0 && Object.keys(localProblems).length === 0;

  const reset = () => {
    setName("");
    setDescription("");
    setScope("personal");
    setIngestion(DEFAULT_INGESTION_CONFIG);
    setEmbeddingModel(null);
    setEmbeddingProvider(null);
    setEmbeddingSecretId(null);
    setRerankSecretId(null);
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
      if (model && model !== embeddingModels?.default) input.embedding_model = model;
      if (provider && provider !== embeddingModels?.default_provider) {
        input.embedding_provider = provider;
      }
      if (embeddingSecretId) input.embedding_secret_id = embeddingSecretId;
      // Both or neither: the backend turns reranking on only when the model and
      // the key arrive together, so a key with no model would be a silent no-op.
      if (rerankSecretId) {
        input.rerank_secret_id = rerankSecretId;
        input.rerank_model = DEFAULT_RERANK_MODEL;
      }
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
      const failure = submitFailure(
        error,
        {
          fields: ["name", "description", ...INGESTION_FORM_FIELDS],
        },
        tErrors,
      );
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
      <DialogContent className={cn(DIALOG_COLUMN, DIALOG_WIDE)}>
        <DialogHeader>
          <DialogTitle>{t("createKnowledgeBase")}</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="flex min-h-0 flex-1 flex-col gap-4">
          <div className="-mx-1 min-h-0 flex-1 scrollbar-thin space-y-4 overflow-y-auto px-1">
            <div data-tour="kb-dialog-name">
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
            </div>
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
            <div className="space-y-1.5" data-tour="kb-dialog-scope">
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
              Folded away like the parsing section: the *model* is frozen at
              creation (the vector column is created at its width), so it
              matters - but the default is right for almost everyone. The
              provider and the key are not frozen and can be changed on the
              collection's own page afterwards.
            */}
            <details
              className="group border-border rounded-lg border"
              data-tour="kb-dialog-embeddings"
            >
              <summary className="text-foreground flex cursor-pointer list-none items-center gap-1.5 p-3 text-sm">
                <ChevronRight className="h-3.5 w-3.5 transition-transform group-open:rotate-90" />
                {t("embeddings")}
                <span className="text-muted-foreground ml-auto text-xs">
                  {model && model !== embeddingModels?.default ? model : t("deploymentDefault")}
                </span>
              </summary>
              <div className="space-y-4 border-t p-4">
                <p className="text-muted-foreground text-xs">{t("frozenAtCreationCollection")}</p>
                {embeddingModels === undefined ? (
                  // In flight and refused are not the same sentence. The model is
                  // frozen at creation - the vector column is made at its width -
                  // so this is the one choice in the dialog nobody can revisit, and
                  // a failure that silently removes it is worth more than a
                  // spinner. Either way the collection is created on the
                  // deployment's default, which is what the message says rather
                  // than leaving somebody to find out afterwards.
                  modelsUnreadable ? (
                    <p className="text-destructive text-sm">{t("modelsUnreadable")}</p>
                  ) : (
                    <p className="text-muted-foreground text-sm">{t("loadingModels")}</p>
                  )
                ) : (
                  <>
                    <EmbeddingProviderFields
                      models={embeddingModels}
                      provider={provider}
                      secretId={embeddingSecretId}
                      onProvider={setEmbeddingProvider}
                      onSecretId={setEmbeddingSecretId}
                      idPrefix="kb-new-embedding"
                    />
                    <div className="space-y-1.5">
                      <Label htmlFor="kb-embedding-model">{t("model")}</Label>
                      {/*
                        Mounted only once the list is, never mounted empty. A Radix
                        select inside a form keeps a hidden native `<select>` in step
                        with its value: the `<option>` elements are registered by the
                        items a render later, so a value that arrives with its
                        options is assigned to a `<select>` that has none, reads back
                        as `""`, and clobbers the state it was about to display.
                      */}
                      <Select value={model} onValueChange={setEmbeddingModel}>
                        <SelectTrigger id="kb-embedding-model">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {offered.map((entry) => (
                            <SelectItem
                              key={entry.model}
                              value={entry.model}
                              // Without this every row answers to the provider's
                              // name - the mark's title is part of the item's text -
                              // and typing a model id finds nothing.
                              textValue={entry.model}
                              // In the list rather than in the row: the trigger draws
                              // whatever the row draws, and both of these are
                              // comparisons against the other options.
                              trailing={
                                <span className="text-muted-foreground ml-auto shrink-0 pl-2 text-xs">
                                  {entry.model === embeddingModels.default
                                    ? t("deploymentDefault")
                                    : t("dimensions", { count: entry.dim })}
                                </span>
                              }
                            >
                              <ProviderRow provider={provider} name={entry.model} />
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <p className="text-muted-foreground text-xs">{t("widthIsFixed")}</p>
                    </div>
                  </>
                )}
              </div>
            </details>

            <details className="group border-border rounded-lg border" data-tour="kb-dialog-rerank">
              <summary className="text-foreground flex cursor-pointer list-none items-center gap-1.5 p-3 text-sm">
                <ChevronRight className="h-3.5 w-3.5 transition-transform group-open:rotate-90" />
                {t("rerank")}
                <span className="text-muted-foreground ml-auto text-xs">
                  {rerankSecretId ? DEFAULT_RERANK_MODEL : t("rerankOff")}
                </span>
              </summary>
              <div className="space-y-4 border-t p-4">
                <p className="text-muted-foreground text-xs">{t("rerankHelp")}</p>
                <div className="space-y-1.5">
                  <Label htmlFor="kb-rerank-key">{t("rerankKey")}</Label>
                  <Select
                    value={rerankSecretId ?? RERANK_OFF}
                    onValueChange={(v) => setRerankSecretId(v === RERANK_OFF ? null : v)}
                  >
                    <SelectTrigger id="kb-rerank-key">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value={RERANK_OFF}>{t("rerankOff")}</SelectItem>
                      {rerankKeys.map((secret) => (
                        <SelectItem key={secret.id} value={secret.id} textValue={secret.name}>
                          <ProviderRow
                            provider={RERANK_KEY_PURPOSE}
                            name={secret.name}
                            hint={secret.hint}
                          />
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <InlineSecret
                    kind="api_key"
                    purpose={RERANK_KEY_PURPOSE}
                    suggestedName={t("rerankKeyName")}
                    onCreated={setRerankSecretId}
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
            <Button
              type="submit"
              disabled={!canSubmit || isSubmitting}
              data-tour="kb-dialog-create"
            >
              {isSubmitting ? t("creating") : t("create")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
