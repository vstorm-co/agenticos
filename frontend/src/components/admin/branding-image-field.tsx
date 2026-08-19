"use client";

import { useRef } from "react";
import { ImageOff, Loader2, Upload } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui";
import type { BrandingImage } from "@/hooks/use-deployment-settings";
import { brandingImageUrl } from "@/lib/branding";

/**
 * Upload or clear one of the two marks, with what is currently stored beside it.
 *
 * The tile shows **what the deployment serves**, never the bytes just chosen from
 * the picker. An optimistic preview of the local file would be a claim the server
 * has not agreed to yet - it refuses anything over 2MB and anything that is not one
 * of four types - so on a rejected upload the tile would sit there showing an image
 * this deployment does not have. While the round trip is in flight the tile says so
 * instead, and the answer carries a new version, which is what re-renders it.
 *
 * That also removes the `blob:` URL the previous version minted, which CodeQL read
 * as DOM text reaching an HTML sink (`js/xss-through-dom`). The value was never
 * attacker-controlled - `createObjectURL` returns `blob:<origin>/<uuid>` - but the
 * simpler component is the better answer than an argument about the taint path.
 *
 * The accepted types are the four this platform accepts everywhere. `accept` is a
 * courtesy to the file picker and not a check: the refusal is the server's, on the
 * declared content type.
 */
const ACCEPTS = "image/png,image/jpeg,image/webp,image/gif";

export function BrandingImageField({
  kind,
  version,
  onUpload,
  onClear,
  busy,
}: {
  kind: BrandingImage;
  /** When the stored image was written, or null when the built-in mark is in use. */
  version: number | null;
  onUpload: (file: File) => void;
  onClear: () => void;
  busy: boolean;
}) {
  const t = useTranslations("pages.admin");
  const input = useRef<HTMLInputElement>(null);
  const stored = brandingImageUrl(kind, version);

  return (
    <div className="border-border bg-card flex items-center gap-4 rounded-xl border p-4">
      <span className="bg-muted text-muted-foreground flex h-16 w-16 shrink-0 items-center justify-center overflow-hidden rounded-lg">
        {busy ? (
          <Loader2 className="h-5 w-5 animate-spin" aria-hidden />
        ) : stored ? (
          // Served through this app's proxy from bytes the API holds. `next/image`
          // would need the route in `remotePatterns` and would re-encode a wordmark
          // it has no size to optimise for.
          // eslint-disable-next-line @next/next/no-img-element
          <img src={stored} alt="" className="h-full w-full object-contain" />
        ) : (
          <ImageOff className="h-5 w-5" aria-hidden />
        )}
      </span>

      <div className="min-w-0 flex-1">
        <p className="text-foreground text-sm font-medium">
          {t(kind === "logo" ? "brandingLogo" : "brandingFavicon")}
        </p>
        <p className="text-muted-foreground mt-0.5 text-xs">
          {t(kind === "logo" ? "brandingLogoHint" : "brandingFaviconHint")}
        </p>
      </div>

      <div className="flex shrink-0 items-center gap-2">
        <input
          ref={input}
          type="file"
          accept={ACCEPTS}
          className="hidden"
          onChange={(event) => {
            const file = event.target.files?.[0];
            // The input is reset so choosing the same file twice fires `change`
            // again - which is what an operator does after a refusal they have
            // since fixed by resizing it.
            event.target.value = "";
            if (file) onUpload(file);
          }}
          data-testid={`${kind}-input`}
        />
        <Button size="sm" variant="outline" disabled={busy} onClick={() => input.current?.click()}>
          <Upload className="h-3.5 w-3.5" />
          {t("brandingUpload")}
        </Button>
        {version !== null && (
          <Button size="sm" variant="outline" disabled={busy} onClick={onClear}>
            {t("brandingReset")}
          </Button>
        )}
      </div>
    </div>
  );
}
