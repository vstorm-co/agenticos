"use client";

import { normalizeIdentifier } from "@/lib/normalize-identifier";
import { useId, useState } from "react";
import { Pencil, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";

import {
  Button,
  ConfirmDialog,
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Input,
  Label,
  Switch,
  Textarea,
} from "@/components/ui";
import { getErrorMessage } from "@/lib/api-error";
import { EmptyState } from "@/components/states";
import { BUILTIN_COMMAND_LIST, isBuiltinEnabled, useSlashCommands } from "@/hooks";
import type { UserSlashCommandRecord } from "@/lib/slash-commands-api";
import { useTranslations } from "next-intl";
import { DIALOG_BODY, DIALOG_COLUMN, DIALOG_CONFIRM } from "@/lib/dialog-sizes";
import { useUnsavedChanges } from "@/hooks/use-unsaved-changes";
import { useUnsavedChangesStore } from "@/stores/unsaved-changes-store";
import { cn } from "@/lib/utils";

const NAME_PATTERN = /^[a-z0-9][a-z0-9-]{0,31}$/;

export function SlashCommandsManager() {
  const tErrors = useTranslations("errors");
  const tc = useTranslations("common");
  const unsavedId = useId();

  const t = useTranslations("settings");
  const tCommands = useTranslations("chat.commands");
  const {
    records,
    isLoading,
    error,
    refresh,
    createCustom,
    updateCustom,
    setBuiltinEnabled,
    remove,
  } = useSlashCommands();

  const customs = records.filter((r) => r.prompt !== null);

  const [editingId, setEditingId] = useState<string | "new" | null>(null);
  const [draftName, setDraftName] = useState("");
  const [draftPrompt, setDraftPrompt] = useState("");
  const [draftEnabled, setDraftEnabled] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [removing, setRemoving] = useState<UserSlashCommandRecord | null>(null);
  const [initial, setInitial] = useState({ name: "", prompt: "", enabled: true });
  const [pendingToggles, setPendingToggles] = useState<ReadonlySet<string>>(() => new Set());

  const openCreate = () => {
    setInitial({ name: "", prompt: "", enabled: true });
    setEditingId("new");
    setDraftName("");
    setDraftPrompt("");
    setDraftEnabled(true);
  };

  const openEdit = (record: UserSlashCommandRecord) => {
    setInitial({ name: record.name, prompt: record.prompt ?? "", enabled: record.is_enabled });
    setEditingId(record.id);
    setDraftName(record.name);
    setDraftPrompt(record.prompt ?? "");
    setDraftEnabled(record.is_enabled);
  };

  const closeDialog = () => {
    if (submitting) return;
    useUnsavedChangesStore.getState().leave(() => setEditingId(null), [unsavedId]);
  };

  async function handleSubmit(): Promise<boolean> {
    if (submitting || editingId === null) return false;
    const original = records.find((record) => record.id === editingId);
    const name = draftName === original?.name ? draftName : normalizeIdentifier(draftName);
    const prompt = draftPrompt.trim();
    if (!NAME_PATTERN.test(name)) {
      toast.error(t("nameMustBeLowercase"));
      return false;
    }
    if (!prompt) {
      toast.error(t("promptCannotBeEmpty"));
      return false;
    }
    setSubmitting(true);
    try {
      if (editingId === "new") {
        await createCustom({ name, prompt });
        toast.success(t("commandCreated", { name }));
      } else {
        await updateCustom(editingId, { name, prompt, is_enabled: draftEnabled });
        toast.success(t("commandUpdated", { name }));
      }
      setEditingId(null);
      return true;
    } catch (e) {
      const msg = getErrorMessage(e, tErrors, t("failedSaveCommand"));
      toast.error(msg);
      return false;
    } finally {
      setSubmitting(false);
    }
  }

  useUnsavedChanges(unsavedId, {
    dirty:
      editingId !== null &&
      (draftName !== initial.name ||
        draftPrompt !== initial.prompt ||
        draftEnabled !== initial.enabled),
    save: handleSubmit,
    discard: () => setEditingId(null),
  });

  function markToggle(name: string, pending: boolean) {
    setPendingToggles((current) => {
      const next = new Set(current);
      if (pending) next.add(name);
      else next.delete(name);
      return next;
    });
  }

  const handleToggleCustom = async (record: UserSlashCommandRecord, next: boolean) => {
    markToggle(record.name, true);
    try {
      await updateCustom(record.id, { is_enabled: next });
    } catch (e) {
      toast.error(getErrorMessage(e, tErrors, t("failedToggle")));
    } finally {
      markToggle(record.name, false);
    }
  };

  const handleToggleBuiltin = async (name: string, next: boolean) => {
    markToggle(name, true);
    try {
      await setBuiltinEnabled(name, next);
    } catch (e) {
      toast.error(getErrorMessage(e, tErrors, t("failedToggle2")));
    } finally {
      markToggle(name, false);
    }
  };

  const handleDelete = async () => {
    if (!removing || deleting) return;
    setDeleting(true);
    try {
      await remove(removing.id);
      toast.success(t("commandDeleted", { name: removing.name }));
      setRemoving(null);
    } catch (e) {
      toast.error(getErrorMessage(e, tErrors, t("failedDelete3")));
    } finally {
      setDeleting(false);
    }
  };

  const editorTitle =
    editingId === "new" ? t("newCustomCommand") : tc("editNamed", { name: `/${initial.name}` });

  return (
    <div className="@container/commands space-y-8">
      {error && (
        <div className="border-destructive/35 bg-destructive/[0.07] text-foreground flex items-center justify-between rounded-xl border px-4 py-3 text-sm">
          <span>{error}</span>
          <Button size="sm" variant="ghost" onClick={() => refresh()}>
            {t("retry")}
          </Button>
        </div>
      )}

      <section className="space-y-3">
        <div className="flex items-baseline justify-between gap-3">
          <div>
            <h3 className="text-foreground text-sm font-semibold">{t("builtCommands")}</h3>
            <p className="text-muted-foreground mt-0.5 text-xs">{t("disableAnyYouDon")}</p>
          </div>
        </div>
        <ul className="border-foreground/10 divide-foreground/8 divide-y rounded-xl border">
          {BUILTIN_COMMAND_LIST.map((cmd) => {
            const enabled = isBuiltinEnabled(cmd.name, records);
            return (
              <li key={cmd.name} className="flex items-center gap-4 px-4 py-3">
                <div className="min-w-0 flex-1">
                  <div className="flex items-baseline gap-2">
                    <code className="text-foreground bg-foreground/8 rounded px-1.5 py-0.5 font-mono text-xs">
                      /{cmd.name}
                    </code>
                    {cmd.action.kind === "client" && (
                      <span className="text-muted-foreground font-mono text-xs tracking-wider uppercase">
                        {t("local")}
                      </span>
                    )}
                  </div>
                  <p className="text-foreground/65 mt-1 text-xs">{tCommands(cmd.descriptionKey)}</p>
                </div>
                <Switch
                  checked={enabled}
                  onCheckedChange={(v) => handleToggleBuiltin(cmd.name, v)}
                  disabled={isLoading || pendingToggles.has(cmd.name)}
                  aria-label={t("toggleCommand", { name: cmd.name })}
                />
              </li>
            );
          })}
        </ul>
      </section>

      <section className="space-y-3">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div className="min-w-0 flex-1 basis-48">
            <h3 className="text-foreground text-sm font-semibold">{t("yourCustomCommands")}</h3>
            <p className="text-muted-foreground mt-0.5 text-xs">
              {t.rich("slashShortcuts", { cmd: (chunks) => <code>{chunks}</code> })}
            </p>
          </div>
          <Button size="sm" className="shrink-0" onClick={openCreate}>
            <Plus className="mr-1 h-3.5 w-3.5" />
            {t("newCommand")}
          </Button>
        </div>

        {customs.length === 0 ? (
          <EmptyState title={t("noCustomCommandsYet")} description={t("createOneSendLong")} />
        ) : (
          <ul className="border-foreground/10 divide-foreground/8 divide-y rounded-xl border">
            {customs.map((record) => (
              <li
                key={record.id}
                className="grid grid-cols-[minmax(0,1fr)_auto] items-start gap-3 px-4 py-3 @max-md/commands:grid-cols-1"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-baseline gap-2">
                    <code className="text-foreground bg-foreground/8 rounded px-1.5 py-0.5 font-mono text-xs break-all">
                      /{record.name}
                    </code>
                  </div>
                  <p className="text-foreground/65 mt-1 line-clamp-2 text-xs">{record.prompt}</p>
                </div>
                <div className="flex shrink-0 items-center justify-end gap-1">
                  <Switch
                    checked={record.is_enabled}
                    onCheckedChange={(v) => handleToggleCustom(record, v)}
                    disabled={isLoading || pendingToggles.has(record.name)}
                    aria-label={t("toggleCommand", { name: record.name })}
                  />
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-sm"
                    onClick={() => openEdit(record)}
                    disabled={pendingToggles.has(record.name)}
                    aria-label={tc("editNamed", { name: `/${record.name}` })}
                  >
                    <Pencil aria-hidden="true" />
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-sm"
                    onClick={() => setRemoving(record)}
                    disabled={pendingToggles.has(record.name)}
                    className="text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
                    aria-label={tc("deleteNamed", { name: `/${record.name}` })}
                  >
                    <Trash2 aria-hidden="true" />
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <Dialog open={editingId !== null} onOpenChange={(o) => !o && closeDialog()}>
        <DialogContent dismissible={!submitting} className={cn(DIALOG_CONFIRM, DIALOG_COLUMN)}>
          <DialogHeader>
            <DialogTitle>{editorTitle}</DialogTitle>
          </DialogHeader>
          <form
            className="flex min-h-0 flex-1 flex-col gap-3"
            onSubmit={(event) => {
              event.preventDefault();
              void handleSubmit();
            }}
          >
            <div className={DIALOG_BODY}>
              <fieldset disabled={submitting} className="min-w-0 space-y-4">
                <legend className="sr-only">{editorTitle}</legend>
                <div>
                  <Label htmlFor="cmd-name">{t("name")}</Label>
                  <div className="mt-1.5 flex items-center gap-2">
                    <span className="text-muted-foreground font-mono text-sm">/</span>
                    <Input
                      id="cmd-name"
                      value={draftName}
                      onChange={(e) => setDraftName(e.target.value)}
                      onBlur={() => {
                        const original = records.find((record) => record.id === editingId);
                        if (draftName !== original?.name)
                          setDraftName(normalizeIdentifier(draftName));
                      }}
                      autoCapitalize="none"
                      autoCorrect="off"
                      spellCheck={false}
                      placeholder={t("todo")}
                      maxLength={32}
                      autoFocus
                    />
                  </div>
                  <p className="text-muted-foreground mt-1 text-xs">
                    {t("lowercaseLettersDigitsHyphens")}
                  </p>
                </div>
                <div>
                  <Label htmlFor="cmd-prompt">{t("prompt")}</Label>
                  <Textarea
                    id="cmd-prompt"
                    value={draftPrompt}
                    onChange={(e) => setDraftPrompt(e.target.value)}
                    placeholder={t("summarizeConversationAsChecklist")}
                    rows={6}
                    maxLength={10_000}
                    className="mt-1.5 font-mono text-base md:text-sm"
                  />
                  <p className="text-muted-foreground mt-1 text-xs">
                    {t.rich("sentAsRegularUserMessage", {
                      name: draftName || t("commandNamePlaceholder"),
                      cmd: (chunks) => <code>{chunks}</code>,
                    })}
                  </p>
                </div>
                {editingId !== "new" && (
                  <div className="flex items-center gap-3">
                    <Switch
                      id="cmd-enabled"
                      checked={draftEnabled}
                      onCheckedChange={setDraftEnabled}
                    />
                    <Label htmlFor="cmd-enabled" className="text-sm font-normal">
                      {t("enabled")}
                    </Label>
                  </div>
                )}
              </fieldset>
            </div>
            <DialogFooter>
              <Button type="button" variant="ghost" onClick={closeDialog} disabled={submitting}>
                {t("cancel")}
              </Button>
              <Button type="submit" loading={submitting}>
                {submitting ? t("saving4") : editingId === "new" ? t("create3") : t("save2")}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
      <ConfirmDialog
        open={removing !== null}
        onOpenChange={(open) => {
          if (!open && !deleting) setRemoving(null);
        }}
        title={tc("deleteNamedConfirm", { name: `/${removing?.name ?? ""}` })}
        description={t("confirmDeleteCommand")}
        confirmLabel={tc("delete")}
        destructive
        loading={deleting}
        onConfirm={handleDelete}
      />
    </div>
  );
}
