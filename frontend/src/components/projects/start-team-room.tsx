"use client";

import { useRef, useState } from "react";
import { Plus } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { Button } from "@/components/ui";
import { useCreateTeamRoom } from "@/hooks/use-room";
import { getErrorMessage } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import { useRouter } from "@/lib/locale-navigation";

export function StartTeamRoom({ projectId }: { projectId: string }) {
  const t = useTranslations("chat.teamRoom");
  const tErrors = useTranslations("errors");
  const { create, isReady } = useCreateTeamRoom();
  const router = useRouter();
  const [creating, setCreating] = useState(false);
  const inFlight = useRef(false);

  async function start() {
    if (!isReady || inFlight.current) return;
    inFlight.current = true;
    setCreating(true);
    try {
      const room = await create(projectId, t("defaultTitle"));
      if (room) router.push(`${ROUTES.CHAT}?id=${room.id}`);
    } catch (error) {
      toast.error(getErrorMessage(error, tErrors, t("createFailed")));
    } finally {
      inFlight.current = false;
      setCreating(false);
    }
  }

  return (
    <Button
      size="sm"
      onClick={() => void start()}
      disabled={!isReady || creating}
      data-tour="project-new-chat"
    >
      <Plus className="h-4 w-4" aria-hidden />
      {creating ? t("creating") : t("newRoom")}
    </Button>
  );
}
