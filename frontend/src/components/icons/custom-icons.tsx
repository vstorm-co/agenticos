"use client";

import { createContext, useContext } from "react";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";

interface CatalogIconList {
  items: string[];
  total: number;
}

const EMPTY: ReadonlySet<string> = new Set();

/**
 * Which custom marks this deployment ships - a context rather than a hook that
 * queries, deliberately: the consumers are the icon components, which render
 * dozens of times per list and in unit tests that mount them bare. The default
 * value is the empty set, so a component outside the provider (a test, a
 * storybook) degrades to the compiled-in marks and the monogram instead of
 * demanding a QueryClient.
 */
const CustomIconsContext = createContext<ReadonlySet<string>>(EMPTY);

/** Fetched once per load; icon files only change when the deployment does. */
export function CustomIconsProvider({ children }: { children: React.ReactNode }) {
  const { data } = useQuery({
    queryKey: qk.catalog.icons(),
    queryFn: () => apiClient.get<CatalogIconList>("/catalog/icons"),
    staleTime: Infinity,
    select: (list): ReadonlySet<string> => new Set(list.items),
  });

  return (
    <CustomIconsContext.Provider value={data ?? EMPTY}>{children}</CustomIconsContext.Provider>
  );
}

/** The names with a custom mark. Empty until the list lands, and outside the provider. */
export function useCustomIcons(): ReadonlySet<string> {
  return useContext(CustomIconsContext);
}

interface CustomMarkProps {
  /** The mark's name as `GET /catalog/icons` listed it. */
  name: string;
  className?: string;
}

/**
 * A deployment-supplied mark, drawn as a `currentColor` silhouette.
 *
 * A CSS mask rather than an `<img>`, and that is the monochrome register
 * enforced by construction: whatever colours the operator's SVG contains, what
 * renders is this element's background - `currentColor`, so it follows the
 * theme like every compiled-in mark. Always decorative, like the icons beside
 * it: every caller prints the name it accompanies.
 */
export function CustomMark({ name, className }: CustomMarkProps) {
  const mask = `url("/api/catalog/icons/${name}")`;
  return (
    <span
      aria-hidden
      className={className}
      style={{
        display: "inline-block",
        backgroundColor: "currentColor",
        maskImage: mask,
        maskRepeat: "no-repeat",
        maskSize: "contain",
        maskPosition: "center",
        WebkitMaskImage: mask,
        WebkitMaskRepeat: "no-repeat",
        WebkitMaskSize: "contain",
        WebkitMaskPosition: "center",
      }}
    />
  );
}
