"use client";

import Image from "next/image";
import { useEffect, useRef, useState } from "react";
import { useArtifactThumbnail } from "@/hooks/use-artifacts";
import { cn } from "@/lib/utils";
import { PreviewSkeleton } from "@/components/ui/preview-skeleton";

function useSeen(ref: React.RefObject<HTMLElement | null>): boolean {
  const [seen, setSeen] = useState(false);
  useEffect(() => {
    const element = ref.current;
    if (seen || element === null || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) setSeen(true);
      },
      { rootMargin: "240px" },
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, [ref, seen]);
  return seen;
}

/** A cached image: opening a listing never runs every App's scripts again. */
export function ArtifactThumbnail({
  artifactId,
  title,
  versionId = null,
}: {
  artifactId: string;
  title: string;
  versionId?: string | null;
}) {
  const box = useRef<HTMLDivElement>(null);
  const seen = useSeen(box);
  const query = useArtifactThumbnail(artifactId, versionId, seen);
  const image = query.data?.state === "ready" ? query.data.image : null;
  const [decoded, setDecoded] = useState<string | null>(null);
  const [failedImage, setFailedImage] = useState<string | null>(null);
  const loading =
    (seen && query.isPending) || (image !== null && decoded !== image && failedImage !== image);
  const line = cn(
    "bg-muted rounded",
    loading && "motion-safe:animate-pulse motion-safe:[animation-iteration-count:2]",
  );
  return (
    <div ref={box} className="relative h-full w-full overflow-hidden">
      {image && failedImage !== image ? (
        <Image
          src={image}
          alt=""
          title={title}
          width={1280}
          height={960}
          unoptimized
          onLoad={() => setDecoded(image)}
          onError={() => setFailedImage(image)}
          className={cn(
            "absolute inset-0 h-full w-full object-cover object-top transition-opacity duration-300 ease-out motion-reduce:transition-none",
            decoded === image ? "opacity-100" : "opacity-0",
          )}
        />
      ) : (
        <div
          aria-hidden
          data-unavailable={
            query.isError ||
            query.data?.state === "unavailable" ||
            (failedImage === image && image !== null)
          }
          className="space-y-2 p-3.5"
        >
          <div className={cn(line, "h-2.5 w-2/5")} />
          <div className={cn(line, "h-2 w-4/5")} />
          <div className={cn(line, "h-2 w-3/5")} />
          <div className="grid grid-cols-3 gap-2 pt-1">
            <div className={cn(line, "h-8")} />
            <div className={cn(line, "h-8")} />
            <div className={cn(line, "h-8")} />
          </div>
        </div>
      )}
      {loading && <PreviewSkeleton />}
    </div>
  );
}
