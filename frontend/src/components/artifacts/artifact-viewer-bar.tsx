"use client";

import { useEffect, useId, useRef, useState } from "react";
import { cn } from "@/lib/utils";
import Link from "next/link";
import {
  Archive,
  ArrowLeft,
  Building2,
  Globe,
  Lock,
  MoreHorizontal,
  ShieldOff,
  UserRoundCog,
  GitPullRequest,
  Trash2,
  UserPlus,
  SlidersHorizontal,
  X,
} from "lucide-react";
import { useTranslations } from "next-intl";

import {
  Badge,
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  IconButton,
} from "@/components/ui";
import { ArtifactActionsMenu } from "@/components/artifacts/artifact-actions-menu";
import { LiveBadge, type LiveHealth } from "@/components/artifacts/live-badge";
import { RestartTourButton } from "@/components/onboarding/restart-tour-button";
import { ROUTES } from "@/lib/constants";
import type { ArtifactActionView, ArtifactDetail } from "@/types/artifact";

/**
 * How far one artifact reaches, in a word, beside its title.
 *
 * "Only people with access" rather than "Private": a private artifact may still
 * carry grants, which this page does not load, and naming it private would tell
 * its owner nobody else can open it when somebody can.
 */
function AccessBadge({ artifact }: { artifact: ArtifactDetail }) {
  const t = useTranslations("artifacts");
  const [Icon, label] =
    artifact.public_url !== null
      ? [Globe, t("accessPublic")]
      : artifact.visibility === "org"
        ? [Building2, t("sharedOrg")]
        : [Lock, t("accessRestricted")];
  return (
    <span className="text-muted-foreground hidden shrink-0 items-center gap-1.5 text-xs md:inline-flex">
      <Icon className="h-3.5 w-3.5" aria-hidden />
      {label}
    </span>
  );
}

interface ArtifactViewerBarProps {
  /** Null while it loads, or once it turned out not to be available. */
  artifact: ArtifactDetail | null;
  /** How the shown version's live data stands; absent when it reads none. */
  live?: LiveHealth;
  /** What the page may ask to run for this viewer; the menu is drawn only when there is some. */
  actions?: readonly ArtifactActionView[];
  /** The version picker, which only the loaded page has. */
  children?: React.ReactNode;
  onShare?: () => void;
  onArchive?: () => void;
  onDelete?: () => void;
  /** Stops the audience reading the page's data; offered while it does. */
  onWithdrawConsent?: () => void;
  /** Opens the dialog that hands the page to another member; offered to who may. */
  onChangeOwner?: () => void;
  /** How many requests wait on the caller to decide; a badge draws only above zero. */
  waitingRequests?: number;
  /** Opens the Share dialog on its Requests. */
  onRequests?: () => void;
}

/**
 * The one strip of console above an artifact: the way back, what it is and who
 * reaches it, and the controls. Archive and Delete sit behind a menu, not beside
 * Share: each takes the page away from everyone who reads it. An archived page
 * has nothing to share - it serves nobody - so only the menu is left, without
 * Archive.
 */
export function ArtifactViewerBar({
  artifact,
  live,
  actions = [],
  children,
  onShare,
  onArchive,
  onDelete,
  onWithdrawConsent,
  onChangeOwner,
  waitingRequests = 0,
  onRequests,
}: ArtifactViewerBarProps) {
  const t = useTranslations("artifacts");
  const tc = useTranslations("common");
  const [controlsOpen, setControlsOpen] = useState(false);
  const controlsId = useId();
  const controlsButton = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!controlsOpen) return;
    const close = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      setControlsOpen(false);
      controlsButton.current?.focus();
    };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [controlsOpen]);
  return (
    <header
      data-tour="artifact-strip"
      className="grid shrink-0 grid-cols-[auto_minmax(0,1fr)] items-center gap-x-2 gap-y-1 border-b px-2 py-2 max-sm:pointer-events-none max-sm:fixed max-sm:inset-x-3 max-sm:top-[calc(max(var(--shell-inset-top,0px),env(safe-area-inset-top))+0.75rem)] max-sm:z-40 max-sm:flex max-sm:justify-between max-sm:border-0 max-sm:p-0 sm:flex sm:min-h-12 sm:gap-2 sm:px-3 sm:py-1.5"
    >
      <IconButton
        asChild
        aria-label={t("backToArtifacts")}
        className="max-sm:bg-background/95 max-sm:pointer-events-auto max-sm:size-11 max-sm:rounded-full max-sm:border max-sm:shadow-sm"
      >
        <Link href={ROUTES.ARTIFACTS}>
          <ArrowLeft className="h-4 w-4" />
        </Link>
      </IconButton>
      <div className="flex min-w-0 flex-1 items-center gap-3 max-sm:sr-only">
        {artifact !== null && (
          <>
            <h1 className="text-foreground truncate text-sm font-medium">{artifact.title}</h1>
            {artifact.environment_name !== null && (
              <Badge
                variant="outline"
                className="hidden shrink-0 md:inline-flex"
                title={t("environmentBadge")}
              >
                {artifact.environment_name}
              </Badge>
            )}
            <AccessBadge artifact={artifact} />
          </>
        )}
      </div>
      {live !== undefined && (
        <span className="max-sm:bg-background/95 shrink-0 max-sm:rounded-full max-sm:border max-sm:px-3 max-sm:py-2 max-sm:shadow-sm">
          <LiveBadge health={live} />
        </span>
      )}
      {artifact !== null && (
        <IconButton
          ref={controlsButton}
          aria-label={t("viewerControls")}
          aria-expanded={controlsOpen}
          aria-controls={controlsId}
          aria-describedby={waitingRequests > 0 ? `${controlsId}-waiting` : undefined}
          onClick={() => setControlsOpen(!controlsOpen)}
          className="bg-background/95 pointer-events-auto relative size-11 rounded-full border shadow-sm sm:hidden"
        >
          {controlsOpen ? <X aria-hidden /> : <SlidersHorizontal aria-hidden />}
          {waitingRequests > 0 && (
            <>
              <span id={`${controlsId}-waiting`} className="sr-only">
                {t("requests.waiting", { count: waitingRequests })}
              </span>
              <Badge variant="warning" aria-hidden className="absolute -top-1 -right-1">
                {waitingRequests}
              </Badge>
            </>
          )}
        </IconButton>
      )}
      {artifact !== null && (
        <div
          id={controlsId}
          className={cn(
            "max-sm:bg-background col-span-2 flex min-w-0 items-center justify-start gap-1 overflow-x-auto max-sm:pointer-events-auto max-sm:absolute max-sm:top-14 max-sm:right-0 max-sm:left-0 max-sm:flex-wrap max-sm:rounded-xl max-sm:border max-sm:p-2 max-sm:shadow-lg sm:max-w-full sm:shrink-0 sm:flex-wrap sm:justify-end sm:gap-2",
            !controlsOpen && "max-sm:hidden",
          )}
        >
          <p className="w-full truncate px-1 pb-1 text-sm font-medium sm:hidden">
            {artifact.title}
          </p>
          {children}
          <ArtifactActionsMenu actions={actions} />
          <RestartTourButton />
          {waitingRequests > 0 && (
            <Button
              size="sm"
              variant="outline"
              aria-label={t("requests.waiting", { count: waitingRequests })}
              data-tour="artifact-requests"
              onClick={onRequests}
            >
              <GitPullRequest className="h-3.5 w-3.5" />
              <span className="sr-only sm:not-sr-only" aria-hidden>
                {t("requests.title")}
              </span>
              <Badge variant="warning" aria-hidden>
                {waitingRequests}
              </Badge>
            </Button>
          )}
          {artifact.archived_at === null && (
            <Button size="sm" className="max-sm:size-11 max-sm:p-0" onClick={onShare}>
              <UserPlus className="h-3.5 w-3.5" />
              {/* The word goes on a phone, where the version it shares would not fit beside it. */}
              <span className="sr-only sm:not-sr-only">{t("share")}</span>
            </Button>
          )}
          {(artifact.can_edit || artifact.may_change_owner) && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <IconButton
                  aria-label={t("moreActions")}
                  data-tour={artifact.may_change_owner ? "artifact-change-owner" : undefined}
                >
                  <MoreHorizontal className="h-4 w-4" />
                </IconButton>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                {artifact.consent?.may_withdraw === true && artifact.consent.shared && (
                  <DropdownMenuItem onSelect={onWithdrawConsent}>
                    <ShieldOff className="h-4 w-4" />
                    {t("consent.withdraw")}
                  </DropdownMenuItem>
                )}
                {artifact.may_change_owner && (
                  <DropdownMenuItem onSelect={onChangeOwner}>
                    <UserRoundCog className="h-4 w-4" />
                    {t("changeOwner.menu")}
                  </DropdownMenuItem>
                )}
                {artifact.can_edit && artifact.archived_at === null && (
                  <DropdownMenuItem onSelect={onArchive}>
                    <Archive className="h-4 w-4" />
                    {t("archive")}
                  </DropdownMenuItem>
                )}
                {artifact.can_edit && (
                  <DropdownMenuItem
                    className="text-destructive focus:text-destructive"
                    onSelect={onDelete}
                  >
                    <Trash2 className="h-4 w-4" />
                    {tc("delete")}
                  </DropdownMenuItem>
                )}
              </DropdownMenuContent>
            </DropdownMenu>
          )}
        </div>
      )}
    </header>
  );
}
