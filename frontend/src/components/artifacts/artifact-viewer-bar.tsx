"use client";

import Link from "next/link";
import { ArrowLeft, Building2, Globe, Lock, MoreHorizontal, Trash2, UserPlus } from "lucide-react";
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
import { ROUTES } from "@/lib/constants";
import type { ArtifactDetail } from "@/types/artifact";

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
  /** The version picker, which only the loaded page has. */
  children?: React.ReactNode;
  onShare?: () => void;
  onDelete?: () => void;
}

/**
 * The one strip of console above an artifact: the way back, what it is and who
 * reaches it, and the controls. Delete sits behind a menu, not beside Share,
 * because it is the one button here that cannot be taken back.
 */
export function ArtifactViewerBar({
  artifact,
  children,
  onShare,
  onDelete,
}: ArtifactViewerBarProps) {
  const t = useTranslations("artifacts");
  const tc = useTranslations("common");
  return (
    <header className="flex h-12 shrink-0 items-center gap-2 border-b px-2 sm:px-3">
      <IconButton asChild aria-label={t("backToArtifacts")}>
        <Link href={ROUTES.ARTIFACTS}>
          <ArrowLeft className="h-4 w-4" />
        </Link>
      </IconButton>
      <div className="flex min-w-0 flex-1 items-center gap-3">
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
      {artifact !== null && (
        <div className="flex shrink-0 items-center gap-2">
          {children}
          <Button size="sm" onClick={onShare}>
            <UserPlus className="h-3.5 w-3.5" />
            {/* The word goes on a phone, where the version it shares would not fit beside it. */}
            <span className="sr-only sm:not-sr-only">{t("share")}</span>
          </Button>
          {artifact.can_edit && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <IconButton aria-label={t("moreActions")}>
                  <MoreHorizontal className="h-4 w-4" />
                </IconButton>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem
                  className="text-destructive focus:text-destructive"
                  onSelect={onDelete}
                >
                  <Trash2 className="h-4 w-4" />
                  {tc("delete")}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          )}
        </div>
      )}
    </header>
  );
}
