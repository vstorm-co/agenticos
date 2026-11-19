"use client";

import { useState, type FormEvent } from "react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useCreateRoomConversation } from "@/hooks";
import { getErrorMessage } from "@/lib/api-error";
import type { Conversation } from "@/types/conversation";

type RoomVisibility = "private" | "public";

interface RoomCreateFormProps {
  onCancel: () => void;
  onCreated: (conversation: Conversation) => void;
}

/** Create a new empty room, then let its owner invite eligible participants. */
export function RoomCreateForm({ onCancel, onCreated }: RoomCreateFormProps) {
  const t = useTranslations("chat.rooms");
  const tErrors = useTranslations("errors");
  const { create } = useCreateRoomConversation();
  const [title, setTitle] = useState("");
  const [visibility, setVisibility] = useState<RoomVisibility>("private");
  const [isCreating, setIsCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const name = title.trim();
    if (!name || isCreating) return;
    setError(null);
    setIsCreating(true);
    try {
      const conversation = await create({ title: name, visibility, participants: [] });
      if (conversation) onCreated(conversation);
    } catch (cause) {
      setError(getErrorMessage(cause, tErrors, t("createFailed")));
    } finally {
      setIsCreating(false);
    }
  };

  return (
    <form onSubmit={(event) => void submit(event)} className="space-y-4">
      <div className="space-y-2">
        <Label htmlFor="room-name">{t("name")}</Label>
        <Input
          id="room-name"
          autoFocus
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          placeholder={t("namePlaceholder")}
          required
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor="room-visibility">{t("visibility")}</Label>
        <Select
          value={visibility}
          onValueChange={(value) => {
            if (value === "private" || value === "public") setVisibility(value);
          }}
        >
          <SelectTrigger id="room-visibility">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="private">{t("private")}</SelectItem>
            <SelectItem value="public">{t("public")}</SelectItem>
          </SelectContent>
        </Select>
        <p className="text-muted-foreground text-xs">
          {t(visibility === "private" ? "privateDescription" : "publicDescription")}
        </p>
      </div>
      {error && (
        <p role="alert" className="text-destructive text-sm">
          {error}
        </p>
      )}
      <div className="flex justify-end gap-2 border-t pt-4">
        <Button type="button" variant="outline" onClick={onCancel} disabled={isCreating}>
          {t("back")}
        </Button>
        <Button type="submit" disabled={!title.trim() || isCreating}>
          {isCreating ? t("creating") : t("createSubmit")}
        </Button>
      </div>
    </form>
  );
}
