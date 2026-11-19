"use client";

import { useState } from "react";
import { ShieldCheck } from "lucide-react";
import { useTranslations } from "next-intl";

import { PlatformToolChecklist } from "@/components/agents/platform-tool-checklist";
import { BrandMark } from "@/components/branding/brand-mark";
import { useBranding } from "@/components/branding/branding-provider";
import { CardStatus, McpServerCard } from "@/components/mcp/mcp-server-card";
import { ErrorState } from "@/components/states";
import {
  Badge,
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Skeleton,
  Switch,
} from "@/components/ui";
import { usePlatformMcpTools } from "@/hooks";
import { getErrorMessage } from "@/lib/api-error";
import { DIALOG_FORM, DIALOG_SCROLL } from "@/lib/dialog-sizes";
import { cn } from "@/lib/utils";
import type { PlatformMcpServerRef } from "@/types/agents";

/** What a new binding starts as: every tool, and every one that changes something held. */
export const NEW_PLATFORM_BINDING: PlatformMcpServerRef = {
  account: "platform",
  allowed_tools: null,
  approval: "writes",
};

/** What the card says about approval: a tool the agent can call let run freely is worth saying. */
function ApprovalStatus({ binding }: { binding: PlatformMcpServerRef }) {
  const t = useTranslations("agents");
  const callable = (name: string) => binding.allowed_tools?.includes(name) ?? true;
  const released = Object.entries(binding.tool_approval ?? {}).filter(
    ([name, mode]) => mode === "never" && callable(name),
  );
  if (released.length > 0) {
    return t("platformSomeRunFreely");
  }
  return binding.approval === "all" ? t("platformAsksEveryCall") : t("platformAsksBeforeWrites");
}

/**
 * This deployment's own MCP server, first in the Builder's gallery (#2190).
 *
 * It needs no connection - it is the platform - and its tools act as whoever the
 * agent runs for, so the card says that rather than whose account it uses. Writes
 * wait for approval from the moment it is switched on; the settings group the
 * tools by what they work on, and only a tool named there runs a change freely.
 */
export function PlatformServerCard({
  binding,
  onChange,
  disabled,
}: {
  binding: PlatformMcpServerRef | null;
  onChange: (next: PlatformMcpServerRef | null) => void;
  disabled?: boolean;
}) {
  const t = useTranslations("agents");
  const { appName } = useBranding();
  const [open, setOpen] = useState(false);
  const isOn = binding !== null;

  return (
    <>
      <McpServerCard
        name={appName}
        icon={null}
        mark={<BrandMark size={24} />}
        url={null}
        description={t("platformServerDescription")}
        badge={<Badge variant="outline">{t("platformServerBadge")}</Badge>}
        headerAction={
          <Switch
            checked={isOn}
            disabled={disabled}
            onCheckedChange={(on) => {
              onChange(on ? NEW_PLATFORM_BINDING : null);
              if (on) setOpen(true);
            }}
            aria-label={t("useServerInAgent", { name: appName })}
          />
        }
        status={
          <CardStatus
            tone={isOn ? "live" : "off"}
            onClick={disabled ? undefined : () => setOpen(true)}
            label={t("serverSettingsNamed", { name: appName })}
          >
            {isOn ? <ApprovalStatus binding={binding} /> : t("platformAsWhoeverAsks")}
          </CardStatus>
        }
        selected={isOn}
        onOpen={disabled ? undefined : () => setOpen(true)}
        dataTour="agent-platform-mcp"
      />
      {/* Mounted only while open: its tool list is a request, and a gallery of
          closed cards should not make one. */}
      {open && (
        <PlatformBindingDialog
          onOpenChange={setOpen}
          name={appName}
          binding={binding}
          onChange={onChange}
          disabled={disabled}
        />
      )}
    </>
  );
}

function PlatformBindingDialog({
  onOpenChange,
  name,
  binding,
  onChange,
  disabled,
}: {
  onOpenChange: (open: boolean) => void;
  name: string;
  binding: PlatformMcpServerRef | null;
  onChange: (next: PlatformMcpServerRef | null) => void;
  disabled?: boolean;
}) {
  const t = useTranslations("agents");
  const tc = useTranslations("common");
  const tErrors = useTranslations("errors");
  const { tools, isLoading, error } = usePlatformMcpTools();

  return (
    <Dialog open onOpenChange={onOpenChange}>
      <DialogContent className={cn(DIALOG_FORM, DIALOG_SCROLL)}>
        <DialogHeader>
          <DialogTitle>{name}</DialogTitle>
          <DialogDescription>{t("platformServerDescription")}</DialogDescription>
        </DialogHeader>

        <p className="bg-muted text-muted-foreground flex items-start gap-2 rounded-lg p-3 text-sm">
          <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
          {t("platformActsAsWhoeverAsks")}
        </p>

        {binding === null ? (
          <Button onClick={() => onChange(NEW_PLATFORM_BINDING)} disabled={disabled}>
            {t("platformUseIt")}
          </Button>
        ) : error ? (
          // A request that failed is said, never drawn as a server with no tools.
          <ErrorState description={getErrorMessage(error, tErrors)} className="py-6" />
        ) : isLoading ? (
          <Skeleton className="h-32 w-full" />
        ) : (
          <PlatformToolChecklist
            tools={tools}
            binding={binding}
            onChange={onChange}
            disabled={disabled}
          />
        )}

        <DialogFooter>
          {binding !== null && (
            <Button
              variant="outline"
              className="mr-auto"
              onClick={() => {
                onChange(null);
                onOpenChange(false);
              }}
              disabled={disabled}
            >
              {t("platformRemove")}
            </Button>
          )}
          <Button onClick={() => onOpenChange(false)}>{tc("done")}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
