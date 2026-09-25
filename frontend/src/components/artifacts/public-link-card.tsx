"use client";

import { Globe, RefreshCw } from "lucide-react";
import { useTranslations } from "next-intl";

import { CopyButton } from "@/components/chat/copy-button";
import {
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Input,
} from "@/components/ui";

interface PublicLinkCardProps {
  publicUrl: string | null;
  /** Whether the caller may turn the link on, rotate it or turn it off. */
  canManage: boolean;
  busy: boolean;
  onEnable: () => void;
  onDisable: () => void;
}

/**
 * The "anyone with the link" address, and the three things a manager does to it.
 *
 * Rotating is the same request as turning it on: the old key stops opening
 * anything at once, which is the answer to a link that went further than meant.
 */
export function PublicLinkCard({
  publicUrl,
  canManage,
  busy,
  onEnable,
  onDisable,
}: PublicLinkCardProps) {
  const t = useTranslations("artifacts");
  return (
    <Card data-tour="artifact-public-link">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Globe className="h-4 w-4" />
          {t("publicLink")}
        </CardTitle>
        <CardDescription>{publicUrl ? t("publicLinkOn") : t("publicLinkNone")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {publicUrl !== null && (
          <div className="flex items-center gap-2">
            <Input
              readOnly
              value={publicUrl}
              aria-label={t("publicLink")}
              className="font-mono text-xs"
            />
            <CopyButton text={publicUrl} />
          </div>
        )}
        {canManage &&
          (publicUrl === null ? (
            <Button size="sm" onClick={onEnable} disabled={busy}>
              {t("createPublicLink")}
            </Button>
          ) : (
            <div className="flex flex-wrap gap-2">
              <Button size="sm" variant="outline" onClick={onEnable} disabled={busy}>
                <RefreshCw className="h-3.5 w-3.5" />
                {t("rotatePublicLink")}
              </Button>
              <Button size="sm" variant="outline" onClick={onDisable} disabled={busy}>
                {t("disablePublicLink")}
              </Button>
            </div>
          ))}
      </CardContent>
    </Card>
  );
}
