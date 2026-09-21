"use client";

import { useEffect, useState, useSyncExternalStore, type ComponentType } from "react";

type EffectProps = {
  images: string[];
  autoReveal: boolean;
  borderRadius?: number;
  className?: string;
  children?: React.ReactNode;
};

export interface GeneratedImageProps {
  /** The picture to resolve into. */
  src: string;
  /** Its alternative text, which survives whichever way it ends up drawn. */
  alt: string;
  /** Matches the effect's corners to the element's own. */
  borderRadius?: number;
  className?: string;
}

/** Whether this browser can create a WebGL context - asked once, cached. */
let webgl: boolean | null = null;

function hasWebgl(): boolean {
  if (webgl !== null) return webgl;
  try {
    webgl = document.createElement("canvas").getContext("webgl2") !== null;
  } catch {
    // jsdom, and any browser that refuses the context outright.
    webgl = false;
  }
  return webgl;
}

/** The answer cannot change within a page's life. */
const subscribeToNothing = () => () => {};

/**
 * A picture that resolves out of a churning mosaic rather than replacing it.
 *
 * The shader *is* the loader, and the image dissolves in out of it - which is
 * why the effect owns the picture rather than being wrapped around one. An
 * earlier version drew the `<img>` first and mounted the effect afterwards; the
 * picture was already there by then, so there was nothing left for it to
 * resolve into and the whole thing was invisible.
 *
 * The plain image is what a browser without WebGL gets, and what the server and
 * the test suite render. `img-fx` carries `three`, several hundred kilobytes
 * that no other page needs, so it is fetched on demand and only where it can
 * actually run.
 */
export function GeneratedImage({ src, alt, borderRadius, className }: GeneratedImageProps) {
  const [Effect, setEffect] = useState<ComponentType<EffectProps> | null>(null);
  const supported = useSyncExternalStore(subscribeToNothing, hasWebgl, () => false);

  useEffect(() => {
    if (!supported) return;
    let live = true;
    void import("img-fx").then((mod) => {
      // The setter form, because the value *is* a component and React would
      // otherwise call it as an updater.
      if (live) setEffect(() => mod.ImageGeneration as unknown as ComponentType<EffectProps>);
    });
    return () => {
      live = false;
    };
  }, [supported]);

  if (!supported) {
    // eslint-disable-next-line @next/next/no-img-element
    return <img src={src} alt={alt} className={className} />;
  }

  if (Effect === null) {
    // Supported, but `img-fx` is still on the wire - and those are not the same
    // state. Drawing the picture here is the one thing this component exists to
    // avoid: it would look finished and then be replaced by the mosaic it was
    // meant to resolve out of, which is the backwards sequence the doc comment
    // above describes.
    //
    // Hidden rather than absent, because the caller sizes this from the image's
    // own dimensions (`w-auto`, `max-h-[28rem]`): an empty box would collapse and
    // the transcript would jump when the effect arrived.
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img src={src} alt={alt} className={className} style={{ visibility: "hidden" }} />
    );
  }

  return (
    <Effect images={[src]} autoReveal borderRadius={borderRadius} className={className}>
      <span className="sr-only">{alt}</span>
    </Effect>
  );
}
