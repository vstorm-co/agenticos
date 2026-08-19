"use client";

import { useRef, useState } from "react";
import { ImageOff, Upload } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui";
import type { BrandingImage } from "@/hooks/use-deployment-settings";
import { brandingImageUrl } from "@/lib/branding";

/**
 * Upload or clear one of the two marks, with what is currently stored beside it.
 *
 * The preview is the whole reason this is not two buttons. An operator uploading a
 * favicon cannot see it in the tab until the page reloads, so without a preview the
 * only feedback is a toast - and "uploaded" is not the same claim as "this is the
 * image you meant".
 *
 * The accepted types are the four this platform accepts everywhere, which is what
 * the server will actually take. `accept` is a courtesy to the file picker and not
 * a check: the refusal is the server's, on the declared content type.
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
  const [chosen, setChosen] = useState<string | null>(null);

  // The uploaded bytes, shown before the round trip finishes. Revoked on the next
  // choice rather than on unmount: a preview replaced is a URL nothing can reach.
  const preview = chosen ?? brandingImageUrl(kind, version);

  const choose = (file: File | undefined) => {
    if (!file) return;
    if (chosen) URL.revokeObjectURL(chosen);
    setChosen(URL.createObjectURL(file));
    onUpload(file);
  };

  return (
    <div className="border-border bg-card flex items-center gap-4 rounded-xl border p-4">
      <span className="bg-muted text-muted-foreground flex h-16 w-16 shrink-0 items-center justify-center overflow-hidden rounded-lg">
        {preview ? (
          // A `blob:` URL from the file picker before the upload finishes, which
          // `next/image` can neither optimise nor load.
          // eslint-disable-next-line @next/next/no-img-element
          <img src={preview} alt="" className="h-full w-full object-contain" />
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
          onChange={(event) => choose(event.target.files?.[0])}
          data-testid={`${kind}-input`}
        />
        <Button size="sm" variant="outline" disabled={busy} onClick={() => input.current?.click()}>
          <Upload className="h-3.5 w-3.5" />
          {t("brandingUpload")}
        </Button>
        {version !== null && (
          <Button
            size="sm"
            variant="outline"
            disabled={busy}
            onClick={() => {
              if (chosen) URL.revokeObjectURL(chosen);
              setChosen(null);
              onClear();
            }}
          >
            {t("brandingReset")}
          </Button>
        )}
      </div>
    </div>
  );
}
