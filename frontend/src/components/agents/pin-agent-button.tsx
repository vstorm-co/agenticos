"use client";

import { useState } from "react";
import { Pin, PinOff } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { Button } from "@/components/ui";
import { useDesktopState, useSetPinned } from "@/hooks/use-desktop";
import { useShell } from "@/hooks/use-shell";
import { isDesktopShell, isMobileShell, reportShellFailure } from "@/lib/desktop/shell";
import { pinToHomeScreen, type PinnableAgent } from "@/lib/mobile/pin";

/**
 * Keep an agent one click from a new chat (#2305, #2097): in the desktop app,
 * "New Chat With" in the Dock icon's menu and the tray's; in the phone app, a
 * shortcut with its face on the home screen. Nothing in a browser, which has
 * neither.
 */
export function PinAgentButton({
  agent,
  disabled = false,
}: {
  agent: PinnableAgent;
  disabled?: boolean;
}) {
  const shell = useShell();
  if (isDesktopShell(shell) && shell.window === "main") {
    return <DesktopPin agent={agent} macos={shell.platform === "macos"} disabled={disabled} />;
  }
  if (isMobileShell(shell)) return <PhonePin agent={agent} disabled={disabled} />;
  return null;
}

function DesktopPin({
  agent,
  macos,
  disabled,
}: {
  agent: PinnableAgent;
  macos: boolean;
  disabled: boolean;
}) {
  const t = useTranslations("agentPin");
  const { data } = useDesktopState();
  const setPinned = useSetPinned();
  const pinned = data?.pinned.some((kept) => kept.id === agent.id) ?? false;
  return (
    <Button
      variant="outline"
      disabled={disabled || !data || setPinned.isPending}
      title={pinned ? undefined : macos ? t("dockHint") : t("trayHint")}
      onClick={() =>
        setPinned.mutate({ agent: { id: agent.id, name: agent.name }, pinned: !pinned })
      }
    >
      {pinned ? <PinOff className="h-4 w-4" /> : <Pin className="h-4 w-4" />}
      {pinned ? t("unpin") : macos ? t("toDock") : t("toTray")}
    </Button>
  );
}

function PhonePin({ agent, disabled }: { agent: PinnableAgent; disabled: boolean }) {
  const t = useTranslations("agentPin");
  const [pinning, setPinning] = useState(false);
  const pin = () => {
    setPinning(true);
    pinToHomeScreen(agent)
      .then((placed) => toast.success(placed ? t("onHomeScreen") : t("inLongPress")))
      .catch((error: unknown) => {
        reportShellFailure("could not pin an agent to the home screen", error);
        toast.error(t("failed"));
      })
      .finally(() => setPinning(false));
  };
  return (
    <Button variant="outline" disabled={disabled || pinning} onClick={pin}>
      <Pin className="h-4 w-4" />
      {t("toHomeScreen")}
    </Button>
  );
}
