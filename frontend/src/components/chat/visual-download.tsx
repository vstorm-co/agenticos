"use client";

import { useState } from "react";
import { Download, FileCode, FileImage } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  IconButton,
} from "@/components/ui";
import { usePublicConfig } from "@/components/public-config/public-config-provider";
import { visualContentBase, type VisualKind } from "@/lib/visuals";
import { downloadSvgPng, downloadVisual, visualToastOptions } from "./visual-actions";

interface VisualDownloadProps {
  title: string;
  kind: VisualKind;
  content: string;
}

/** SVGs offer a PNG beside their source; other drawings keep their existing download. */
export function VisualDownload({ title, kind, content }: VisualDownloadProps) {
  const t = useTranslations("chat.visuals");
  const { artifactUrl } = usePublicConfig();
  const [pending, setPending] = useState(false);
  const [failed, setFailed] = useState(false);
  const source = () =>
    downloadVisual(
      title,
      kind,
      content,
      new URL(visualContentBase(artifactUrl), window.location.href).href,
    );

  const png = async () => {
    setFailed(false);
    setPending(true);
    try {
      await downloadSvgPng(title, content);
    } catch {
      setFailed(true);
      toast.error(t("pngDownloadFailed"), visualToastOptions());
    } finally {
      setPending(false);
    }
  };

  const trigger = (
    <IconButton
      aria-label={pending ? t("preparingPng") : t("download")}
      title={pending ? t("preparingPng") : t("download")}
      loading={pending}
      onClick={kind === "svg" ? undefined : source}
    >
      <Download className="size-3.5" />
    </IconButton>
  );

  if (kind !== "svg") return trigger;
  return (
    <div className="relative">
      <DropdownMenu>
        <DropdownMenuTrigger asChild disabled={pending}>
          {trigger}
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem onSelect={source}>
            <FileCode />
            {t("downloadSvg")}
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={() => void png()}>
            <FileImage />
            {t("downloadPng")}
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      {failed && (
        <p
          role="alert"
          className="bg-popover text-popover-foreground absolute top-full right-0 z-50 mt-2 w-64 rounded-lg border p-3 text-xs shadow-lg"
        >
          {t("pngDownloadFailed")}
        </p>
      )}
    </div>
  );
}
