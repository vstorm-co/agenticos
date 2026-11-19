"use client";

import { useState } from "react";
import { Users } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { useJoinPublicRoom, useRoomDirectory } from "@/hooks";
import { getErrorMessage } from "@/lib/api-error";
import { DIALOG_FORM, DIALOG_SCROLL } from "@/lib/dialog-sizes";
import { cn } from "@/lib/utils";
import type { Conversation } from "@/types/conversation";
import { RoomCreateForm } from "./room-create-form";
import { RoomDirectoryList } from "./room-directory-list";

interface RoomDirectoryDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSelectConversation: (conversation: Conversation) => void;
  onCreated: (conversation: Conversation) => void;
}

/** Browse public rooms and create a private or public room from the chat sidebar. */
export function RoomDirectoryDialog({
  open,
  onOpenChange,
  onSelectConversation,
  onCreated,
}: RoomDirectoryDialogProps) {
  const t = useTranslations("chat.rooms");
  const tErrors = useTranslations("errors");
  const directory = useRoomDirectory();
  const joinRoom = useJoinPublicRoom();
  const [creating, setCreating] = useState(false);
  const [joiningId, setJoiningId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleJoin = async (id: string) => {
    if (joinRoom.isJoining) return;
    setJoiningId(id);
    setError(null);
    try {
      const conversation = await joinRoom.join(id);
      if (conversation) {
        onOpenChange(false);
        onSelectConversation(conversation);
      }
    } catch (cause) {
      setError(getErrorMessage(cause, tErrors, t("joinFailed")));
    } finally {
      setJoiningId(null);
    }
  };

  const handleCreated = (conversation: Conversation) => {
    onOpenChange(false);
    onCreated(conversation);
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (!nextOpen) setCreating(false);
        onOpenChange(nextOpen);
      }}
    >
      <DialogContent className={cn(DIALOG_FORM, DIALOG_SCROLL)} dismissible={!joinRoom.isJoining}>
        <DialogHeader>
          <DialogTitle>{creating ? t("createTitle") : t("title")}</DialogTitle>
          <DialogDescription>
            {creating ? t("createDescription") : t("description")}
          </DialogDescription>
        </DialogHeader>
        {creating ? (
          <RoomCreateForm onCancel={() => setCreating(false)} onCreated={handleCreated} />
        ) : (
          <div className="min-h-0 space-y-4 overflow-y-auto">
            <div className="flex justify-end">
              <Button size="sm" onClick={() => setCreating(true)}>
                <Users className="size-4" aria-hidden />
                {t("create")}
              </Button>
            </div>
            {error && (
              <p role="alert" className="text-destructive text-sm">
                {error}
              </p>
            )}
            <RoomDirectoryList
              rooms={directory.rooms}
              isLoading={directory.isLoading}
              error={directory.error}
              isJoining={joinRoom.isJoining}
              joiningId={joiningId}
              onRetry={() => void directory.refetch()}
              onJoin={(id) => void handleJoin(id)}
            />
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
