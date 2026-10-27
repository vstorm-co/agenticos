"use client";

import {
  AudiencePicker,
  EVERYONE,
  audiencePayload,
  type Audience,
} from "@/components/sharing/audience-picker";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { MoreOptions } from "@/components/ui/more-options";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { EmbeddingProviderFields, useEmbeddingProviders } from "@/components/kb/embedding-picker";
import { IngestionSettings, ParserCards } from "@/components/kb/ingestion-settings";
import { ProviderRow } from "@/components/vault/provider-row";
import { useKnowledgeBases } from "@/hooks";
import { submitFailure } from "@/lib/api-error";
import {
  DEFAULT_INGESTION_CONFIG,
  INGESTION_FORM_FIELDS,
  ingestionProblems,
  sameIngestion,
} from "@/lib/ingestion-config";
import { cn } from "@/lib/utils";
import type { CreateKnowledgeBaseInput, IngestionConfig } from "@/types";
import { useTranslations } from "next-intl";
import { DIALOG_BODY, DIALOG_COLUMN, DIALOG_FORM } from "@/lib/dialog-sizes";

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
  // The organization by default (#2072). "Only me" is a personal collection; the
  // other two are an organization one, open or shared with chosen groups.
  const [audience, setAudience] = useState<Audience>(EVERYONE);
  const [ingestion, setIngestion] = useState<IngestionConfig>(DEFAULT_INGESTION_CONFIG);
  const [embeddingModel, setEmbeddingModel] = useState<string | null>(null);
  const [embeddingProvider, setEmbeddingProvider] = useState<string | null>(null);
  const [embeddingSecretId, setEmbeddingSecretId] = useState<string | null>(null);
  const [embeddingBaseUrl, setEmbeddingBaseUrl] = useState("");
  const [embeddingEndpointId, setEmbeddingEndpointId] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errors, setErrors] = useState<Readonly<Record<string, string>>>({});
  const { createKB } = useKnowledgeBases();
  const { models: embeddingModels, unreadable: modelsUnreadable } = useEmbeddingProviders();
  // Whose endpoint the models on offer belong to. The provider decides both the
  // model list and which vault keys can pay, so it is resolved before either -
  // and a model the chosen provider does not serve is not a model this
  // collection can be created with.
  // No deployment default for either: the first provider the catalog lists is
  // preselected so the model list has something to show, the first model that
  // provider serves is preselected for the same reason, and the key or server
  // beside them stays empty until somebody chooses one.
  const provider = embeddingProvider ?? embeddingModels?.providers[0]?.provider ?? "";
  const providerEntry = embeddingModels?.providers.find((item) => item.provider === provider);
  const offered = providerEntry?.models ?? [];
  const firstOffered = offered[0]?.model ?? "";
  const model = offered.some((entry) => entry.model === embeddingModel)
    ? (embeddingModel ?? firstOffered)
    : firstOffered;

  // Nobody has chosen an ingestion configuration until it differs from what is
  // shown, and sending one they did not choose is not a harmless default: the
  // API fills a *missing* object from this deployment's settings, which an
  // operator may have set to something other than the platform's. Posting the
  // form's starting values would quietly overrule that.
  const chosen = !sameIngestion(ingestion, DEFAULT_INGESTION_CONFIG);
  const localProblems = chosen ? ingestionProblems(ingestion, t) : {};
  const canSubmit = name.trim().length > 0 && Object.keys(localProblems).length === 0;
  // The parsing details open themselves when they hold something required -
  // LlamaParse's key - or something refused, and never close themselves: a
  // fold shutting the moment its last problem is fixed takes the field being
  // typed into with it.
  const [detailsOpen, setDetailsOpen] = useState(false);
  const parsingNeedsAttention =
    ingestion.pdf_parser === "llamaparse" ||
    Object.keys(localProblems).length > 0 ||
    INGESTION_FORM_FIELDS.some((field) => field !== "pdf_parser" && field in errors);
  if (parsingNeedsAttention && !detailsOpen) setDetailsOpen(true);

  const reset = () => {
    setName("");
    setDescription("");
    setAudience(EVERYONE);
    setIngestion(DEFAULT_INGESTION_CONFIG);
    setEmbeddingModel(null);
    setEmbeddingProvider(null);
    setEmbeddingSecretId(null);
    setEmbeddingEndpointId(null);
    setEmbeddingBaseUrl("");
    setDetailsOpen(false);
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
        scope: audience.mode === "private" ? "personal" : "org",
        group_ids: audiencePayload(audience).group_ids,
        user_ids: audiencePayload(audience).user_ids,
      };
      // The key is absent rather than undefined: "inherit the deployment's
      // defaults" is a thing the API is told by being told nothing.
      if (chosen) input.ingestion_config = ingestion;
      // The model, the provider and the key or server are always sent: the API
      // has no deployment default for any of them, and a missing key comes back
      // as a refusal on that field rather than as a collection that cannot
      // index its first document.
      if (model) input.embedding_model = model;
      if (provider) input.embedding_provider = provider;
      if (embeddingSecretId) input.embedding_secret_id = embeddingSecretId;
      if (embeddingEndpointId) input.embedding_endpoint_id = embeddingEndpointId;
      if (provider === "openrouter" && embeddingBaseUrl.trim())
        input.embedding_base_url = embeddingBaseUrl.trim();
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
          fields: [
            "name",
            "description",
            "embedding_provider",
            "embedding_secret_id",
            "embedding_endpoint_id",
            "embedding_base_url",
            ...INGESTION_FORM_FIELDS,
          ],
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
      <DialogContent className={cn(DIALOG_COLUMN, DIALOG_FORM)}>
        <DialogHeader>
          <DialogTitle>{t("createKnowledgeBase")}</DialogTitle>
          <DialogDescription>{t("createKbDescription")}</DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="flex min-h-0 flex-1 flex-col gap-4">
          <div className={cn(DIALOG_BODY, "scrollbar-thin space-y-6")}>
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
            <div className="space-y-1.5" data-tour="kb-dialog-scope">
              <Label>{t("whoCanSearchIt")}</Label>
              <AudiencePicker value={audience} onChange={setAudience} />
            </div>

            {/*
              Open, not folded: the model is frozen at creation (the vector
              column is made at its width) and the key decides whose account
              pays, so these are choices somebody has to see to make - and a
              collection without a key is refused.
            */}
            <section className="space-y-3" data-tour="kb-dialog-embeddings">
              <div className="space-y-1">
                <h3 className="text-foreground text-sm font-semibold">{t("embeddings")}</h3>
                <p className="text-muted-foreground text-xs">{t("frozenAtCreationCollection")}</p>
              </div>
              {embeddingModels === undefined ? (
                // In flight and refused are not the same sentence. With no list
                // there is no provider, model or key to name, so the collection
                // will be refused - which is what the message says rather than
                // leaving somebody to find out on submit.
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
                    endpointId={embeddingEndpointId}
                    baseUrl={embeddingBaseUrl}
                    onBaseUrl={setEmbeddingBaseUrl}
                    onProvider={setEmbeddingProvider}
                    onSecretId={setEmbeddingSecretId}
                    onEndpointId={setEmbeddingEndpointId}
                    idPrefix="kb-new-embedding"
                  />
                  {(errors.embedding_provider ??
                    errors.embedding_secret_id ??
                    errors.embedding_endpoint_id ??
                    errors.embedding_base_url) !== undefined && (
                    <p className="text-destructive text-xs">
                      {errors.embedding_provider ??
                        errors.embedding_secret_id ??
                        errors.embedding_endpoint_id ??
                        errors.embedding_base_url}
                    </p>
                  )}
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
                            // whatever the row draws, and the width is a comparison
                            // against the other options.
                            trailing={
                              <span className="text-muted-foreground ml-auto shrink-0 pl-2 text-xs">
                                {t("dimensions", { count: entry.dim })}
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
            </section>

            {/*
              The parser is the one parsing decision most people make, so it is
              three choices on the page; chunking, OCR and image descriptions
              wait folded. The fold opens itself when it holds something
              required - LlamaParse's key - or something refused.
            */}
            <section className="space-y-3">
              <h3 className="text-foreground text-sm font-semibold">
                {t("howDocumentsAreParsed")}
              </h3>
              <ParserCards
                value={ingestion}
                onChange={setIngestion}
                disabled={isSubmitting}
                error={errors.pdf_parser}
              />
              <MoreOptions
                label={t("parsingDetails")}
                open={detailsOpen}
                onOpenChange={setDetailsOpen}
              >
                <p className="text-muted-foreground text-xs">{t("leftAloneCollectionInherits")}</p>
                <IngestionSettings
                  idPrefix="kb-new"
                  value={ingestion}
                  onChange={setIngestion}
                  errors={{ ...localProblems, ...errors }}
                  disabled={isSubmitting}
                  withoutParser
                />
              </MoreOptions>
            </section>

            <MoreOptions label={t("moreOptions")}>
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
            </MoreOptions>
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
