"use client";

import { useState } from "react";
import { Pencil, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";

import {
  Button,
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

const NAME_PATTERN = /^[a-z0-9][a-z0-9-]{0,31}$/;

export function SlashCommandsManager() {
  const tErrors = useTranslations("errors");

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

  const openCreate = () => {
    setEditingId("new");
    setDraftName("");
    setDraftPrompt("");
    setDraftEnabled(true);
  };

  const openEdit = (record: UserSlashCommandRecord) => {
    setEditingId(record.id);
    setDraftName(record.name);
    setDraftPrompt(record.prompt ?? "");
    setDraftEnabled(record.is_enabled);
  };

  const closeDialog = () => {
    if (submitting) return;
    setEditingId(null);
  };

  const handleSubmit = async () => {
    const name = draftName.trim().toLowerCase();
    const prompt = draftPrompt.trim();
    if (!NAME_PATTERN.test(name)) {
      toast.error(t("nameMustBeLowercase"));
      return;
    }
    if (!prompt) {
      toast.error(t("promptCannotBeEmpty"));
      return;
    }
    setSubmitting(true);
    try {
      if (editingId === "new") {
        await createCustom({ name, prompt });
        toast.success(`/${name} created.`);
      } else if (editingId) {
        await updateCustom(editingId, { name, prompt, is_enabled: draftEnabled });
        toast.success(`/${name} updated.`);
      }
      setEditingId(null);
    } catch (e) {
      const msg = getErrorMessage(e, tErrors, t("failedSaveCommand"));
      toast.error(msg);
    } finally {
      setSubmitting(false);
    }
  };

  const handleToggleCustom = async (record: UserSlashCommandRecord, next: boolean) => {
    try {
      await updateCustom(record.id, { is_enabled: next });
    } catch (e) {
      toast.error(e instanceof Error ? e.message : t("failedToggle"));
    }
  };

  const handleToggleBuiltin = async (name: string, next: boolean) => {
    try {
      await setBuiltinEnabled(name, next);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : t("failedToggle2"));
    }
  };

  const handleDelete = async (record: UserSlashCommandRecord) => {
    if (!confirm(`Delete /${record.name}?`)) return;
    try {
      await remove(record.id);
      toast.success(`/${record.name} deleted.`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : t("failedDelete3"));
    }
  };

  return (
    <div className="space-y-8">
      {error && (
        <div className="border-destructive/30 bg-destructive/5 text-destructive flex items-center justify-between rounded-xl border px-4 py-3 text-sm">
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
            <p className="text-foreground/55 mt-0.5 text-xs">{t("disableAnyYouDon")}</p>
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
                      <span className="text-foreground/45 font-mono text-[10px] tracking-wider uppercase">
                        {t("local")}
                      </span>
                    )}
                  </div>
                  <p className="text-foreground/65 mt-1 text-xs">{tCommands(cmd.descriptionKey)}</p>
                </div>
                <Switch
                  checked={enabled}
                  onCheckedChange={(v) => handleToggleBuiltin(cmd.name, v)}
                  disabled={isLoading}
                  aria-label={`Toggle /${cmd.name}`}
                />
              </li>
            );
          })}
        </ul>
      </section>

      <section className="space-y-3">
        <div className="flex items-baseline justify-between gap-3">
          <div>
            <h3 className="text-foreground text-sm font-semibold">{t("yourCustomCommands")}</h3>
            <p className="text-foreground/55 mt-0.5 text-xs">
              {t("slashShortcutsLead")}
              {t("chatSendsStoredPrompt")}
            </p>
          </div>
          <Button size="sm" onClick={openCreate}>
            <Plus className="mr-1 h-3.5 w-3.5" />
            {t("newCommand")}
          </Button>
        </div>

        {customs.length === 0 ? (
          <EmptyState title={t("noCustomCommandsYet")} description={t("createOneSendLong")} />
        ) : (
          <ul className="border-foreground/10 divide-foreground/8 divide-y rounded-xl border">
            {customs.map((record) => (
              <li key={record.id} className="flex items-start gap-4 px-4 py-3">
                <div className="min-w-0 flex-1">
                  <div className="flex items-baseline gap-2">
                    <code className="text-foreground bg-foreground/8 rounded px-1.5 py-0.5 font-mono text-xs">
                      /{record.name}
                    </code>
                  </div>
                  <p className="text-foreground/65 mt-1 line-clamp-2 text-xs">{record.prompt}</p>
                </div>
                <Switch
                  checked={record.is_enabled}
                  onCheckedChange={(v) => handleToggleCustom(record, v)}
                  aria-label={`Toggle /${record.name}`}
                />
                <button
                  type="button"
                  onClick={() => openEdit(record)}
                  className="text-foreground/55 hover:bg-foreground/5 hover:text-foreground inline-flex h-7 w-7 items-center justify-center rounded-md transition-colors"
                  title={t("edit")}
                  aria-label={t("edit2")}
                >
                  <Pencil className="h-3.5 w-3.5" />
                </button>
                <button
                  type="button"
                  onClick={() => handleDelete(record)}
                  className="text-foreground/55 hover:bg-destructive/10 hover:text-destructive inline-flex h-7 w-7 items-center justify-center rounded-md transition-colors"
                  title={t("delete")}
                  aria-label={t("delete2")}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <Dialog open={editingId !== null} onOpenChange={(o) => !o && closeDialog()}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {editingId === "new" ? t("newCustomCommand") : `Edit /${draftName}`}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <Label htmlFor="cmd-name">{t("name")}</Label>
              <div className="mt-1.5 flex items-center gap-2">
                <span className="text-foreground/45 font-mono text-sm">/</span>
                <Input
                  id="cmd-name"
                  value={draftName}
                  onChange={(e) => setDraftName(e.target.value.toLowerCase())}
                  placeholder={t("todo")}
                  maxLength={32}
                  autoFocus
                />
              </div>
              <p className="text-foreground/45 mt-1 text-[11px]">
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
                className="mt-1.5 font-mono text-sm"
              />
              <p className="text-foreground/45 mt-1 text-[11px]">
                {t.rich("sentAsRegularUserMessage", {
                  name: draftName || t("commandNamePlaceholder"),
                  cmd: (chunks) => <code>{chunks}</code>,
                })}
              </p>
            </div>
            {editingId !== "new" && (
              <div className="flex items-center gap-3">
                <Switch id="cmd-enabled" checked={draftEnabled} onCheckedChange={setDraftEnabled} />
                <Label htmlFor="cmd-enabled" className="text-sm font-normal">
                  {t("enabled")}
                </Label>
              </div>
            )}
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={closeDialog} disabled={submitting}>
              {t("cancel")}
            </Button>
            <Button onClick={handleSubmit} disabled={submitting}>
              {submitting ? t("saving4") : editingId === "new" ? t("create3") : t("save2")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
