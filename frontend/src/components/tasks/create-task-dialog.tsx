"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { MarkdownCellEditor } from "@/components/tables/markdown-cell-editor";
import { AgentAvatar } from "@/components/agents/agent-avatar";
import {
  Alert,
  AlertDescription,
  Button,
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
  FormField,
  Input,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { useAgents } from "@/hooks/use-agents";
import { useDurableTasks } from "@/hooks/use-durable-tasks";
import { getErrorMessage } from "@/lib/api-error";
import type { TaskBoard } from "@/lib/tasks-api";
import { useAuthStore } from "@/stores/auth-store";

export function CreateTaskDialog({
  open,
  onOpenChange,
  board,
}: {
  open: boolean;
  onOpenChange: (value: boolean) => void;
  board?: TaskBoard;
}) {
  const t = useTranslations("durableTasks");
  const errors = useTranslations("errors");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [agent, setAgent] = useState("me");
  const [start, setStart] = useState("");
  const [due, setDue] = useState("");
  const user = useAuthStore((state) => state.user?.id);
  const { create } = useDurableTasks();
  const { agents, error: agentError } = useAgents();
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    await create.mutateAsync({
      title,
      description,
      status: "planned",
      next_actor: agent === "me" ? "user" : "agent",
      scope: board?.scope_kind ?? "private",
      scope_id: board?.scope_id,
      assignee_user_id: agent === "me" ? (user ?? null) : null,
      assignee_agent_id: agent === "me" ? null : agent,
      start_at: start ? new Date(start).toISOString() : null,
      due_at: due ? new Date(due).toISOString() : null,
    });
    onOpenChange(false);
  }
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <form onSubmit={(event) => void submit(event).catch(() => undefined)} className="space-y-5">
          <DialogHeader>
            <DialogTitle>{t("newTask")}</DialogTitle>
            <DialogDescription>{t("createHint")}</DialogDescription>
          </DialogHeader>
          <FormField label={t("title")} htmlFor="task-title">
            <Input
              id="task-title"
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              maxLength={160}
              required
            />
          </FormField>
          <FormField label={t("description")} htmlFor="task-description">
            <MarkdownCellEditor
              id="task-description"
              label={t("description")}
              value={description}
              onChange={setDescription}
              onCommit={() => {}}
              showMetadata={false}
            />
          </FormField>
          <FormField label={t("assignee")} htmlFor="task-assignee">
            <Select value={agent} onValueChange={setAgent}>
              <SelectTrigger id="task-assignee">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="me">{t("me")}</SelectItem>
                {agents
                  .filter((item) => item.can_run && item.current_version_id)
                  .map((item) => (
                    <SelectItem key={item.id} value={item.id} textValue={item.name}>
                      <span className="flex items-center gap-2">
                        <AgentAvatar
                          agentId={item.id}
                          slug={item.slug}
                          hasAvatar={item.has_avatar}
                          colorSlot={item.avatar_color}
                          size="sm"
                        />
                        {item.name}
                      </span>
                    </SelectItem>
                  ))}
              </SelectContent>
            </Select>
          </FormField>
          {agentError && <p className="text-muted-foreground text-sm">{t("agentsUnavailable")}</p>}
          <div className="grid gap-4 sm:grid-cols-2">
            <FormField
              label={t("start")}
              htmlFor="task-start"
              description={t(agent === "me" ? "reminderHint" : "startHint")}
            >
              <Input
                id="task-start"
                type="datetime-local"
                value={start}
                onChange={(event) => setStart(event.target.value)}
              />
            </FormField>
            <FormField label={t("due")} htmlFor="task-due" description={t("dueHint")}>
              <Input
                id="task-due"
                type="datetime-local"
                value={due}
                onChange={(event) => setDue(event.target.value)}
              />
            </FormField>
          </div>
          <p className="text-muted-foreground text-xs">{t("localTime")}</p>
          {create.error && (
            <Alert variant="destructive">
              <AlertDescription>{getErrorMessage(create.error, errors)}</AlertDescription>
            </Alert>
          )}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {t("cancel")}
            </Button>
            <Button type="submit" disabled={!title.trim() || create.isPending}>
              {t(create.isPending ? "saving" : "create")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
