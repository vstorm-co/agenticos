"use client";

import { useEffect, useRef, useState } from "react";
import Image, { type ImageProps } from "next/image";

import { getFileUrl } from "@/lib/file-api";
import { keptFile } from "@/lib/offline/device-cache";

/**
 * A chat attachment's picture, from the server - and, where that fails, from
 * the copy the apps keep of a recent conversation's files (#2097), so a photo
 * in a thread read offline is still there. Nothing kept is the broken image
 * it was.
 */
export function KeptImage({ fileId, alt, ...props }: Omit<ImageProps, "src"> & { fileId: string }) {
  const [src, setSrc] = useState(() => getFileUrl(fileId));
  const fellBack = useRef(false);

  useEffect(
    () => () => {
      if (src.startsWith("blob:")) URL.revokeObjectURL(src);
    },
    [src],
  );

  return (
    <Image
      {...props}
      alt={alt}
      src={src}
      unoptimized
      onError={() => {
        if (fellBack.current) return;
        fellBack.current = true;
        void keptFile(fileId).then((blob) => {
          if (blob) setSrc(URL.createObjectURL(blob));
        });
      }}
    />
  );
}
