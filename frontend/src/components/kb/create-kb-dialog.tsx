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
          <DialogTitle>Create knowledge base</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="flex min-h-0 flex-1 flex-col gap-4">
          <div className="-mx-1 min-h-0 flex-1 space-y-4 overflow-y-auto px-1">
            <FormField label="Name" htmlFor="kb-name" error={errors.name}>
              <Input
                id="kb-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Product docs"
                maxLength={MAX_NAME}
                autoFocus
              />
            </FormField>
            <FormField
              label="Description (optional)"
              htmlFor="kb-description"
              error={errors.description}
            >
              <Textarea
                id="kb-description"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="What documents will this KB contain?"
                maxLength={MAX_DESCRIPTION}
                rows={2}
              />
            </FormField>
            <div className="space-y-1.5">
              <Label htmlFor="kb-scope">Scope</Label>
              <Select value={scope} onValueChange={(v) => setScope(v as KBScope)}>
                <SelectTrigger id="kb-scope">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="personal">Personal - only you</SelectItem>
                  <SelectItem value="org">Organization - all members</SelectItem>
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
                Embeddings
                <span className="text-muted-foreground ml-auto text-xs">
                  {embeddingModel && embeddingModel !== embeddingModels?.default
                    ? embeddingModel
                    : "deployment default"}
                </span>
              </summary>
              <div className="space-y-4 border-t p-4">
                <p className="text-muted-foreground text-xs">
                  Frozen at creation: the collection&apos;s vectors are produced by this model and
                  cannot be re-indexed under another one later. The key decides whose account pays
                  for embedding.
                </p>
                <div className="space-y-1.5">
                  <Label htmlFor="kb-embedding-model">Model</Label>
                  <Select
                    value={embeddingModel ?? embeddingModels?.default ?? ""}
                    onValueChange={setEmbeddingModel}
                    disabled={!embeddingModels}
                  >
                    <SelectTrigger id="kb-embedding-model">
                      <SelectValue placeholder="Loading models…" />
                    </SelectTrigger>
                    <SelectContent>
                      {(embeddingModels?.models ?? []).map((entry) => (
                        <SelectItem key={entry.model} value={entry.model}>
                          {entry.model}
                          {entry.model === embeddingModels?.default ? " (default)" : ""}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="kb-embedding-key">Key</Label>
                  <Select
                    value={embeddingSecretId ?? DEPLOYMENT_KEY}
                    onValueChange={(v) => setEmbeddingSecretId(v === DEPLOYMENT_KEY ? null : v)}
                  >
                    <SelectTrigger id="kb-embedding-key">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value={DEPLOYMENT_KEY}>Deployment key</SelectItem>
                      {embeddingKeys.map((secret) => (
                        <SelectItem key={secret.id} value={secret.id}>
                          {secret.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  {embeddingKeys.length === 0 && (
                    <p className="text-muted-foreground text-xs">
                      Add an OpenRouter key in the vault to bill embeddings to this organization.
                    </p>
                  )}
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
                How documents are parsed
                <span className="text-muted-foreground ml-auto text-xs">
                  {chosen ? "customized" : "deployment defaults"}
                </span>
              </summary>
              <div className="space-y-4 border-t p-4">
                <p className="text-muted-foreground text-xs">
                  Left alone, this collection inherits whatever defaults the deployment is
                  configured with. The values below are the platform&apos;s; changing any one of
                  them sends all of them, and they become this collection&apos;s until somebody
                  edits them.
                </p>
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
              Cancel
            </Button>
            <Button type="submit" disabled={!canSubmit || isSubmitting}>
              {isSubmitting ? "Creating..." : "Create"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
