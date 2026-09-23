"use client";

import Link from "next/link";

import { BrandMark } from "@/components/branding/brand-mark";
import { useBranding } from "@/components/branding/branding-provider";
import { ROUTES } from "@/lib/constants";

/**
 * The product's name, as a link home.
 *
 * Shared by the two places that are ever the top-left of the screen: the head
 * of the column above `md`, and the mobile bar below it. One of them is always
 * on screen and never both.
 *
 * `markOnly` is the collapsed column, where 56px has room for the mark and not
 * for the word beside it. The link keeps its destination and its accessible
 * name either way - the name moves into `title`/`aria-label` rather than being
 * dropped, so a rail is still navigable by anything that reads one.
 */
export function BrandLink({ markOnly = false }: { markOnly?: boolean }) {
  const { appName } = useBranding();
  return (
    <Link
      href={ROUTES.DASHBOARD}
      title={markOnly ? appName : undefined}
      aria-label={markOnly ? appName : undefined}
      className="focus-visible:ring-ring flex items-center gap-2 rounded-md text-sm font-bold tracking-tight outline-none focus-visible:ring-1"
    >
      <BrandMark />
      {markOnly ? null : appName}
    </Link>
  );
}
