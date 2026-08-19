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
 */
export function BrandLink() {
  const { appName } = useBranding();
  return (
    <Link
      href={ROUTES.DASHBOARD}
      className="focus-visible:ring-ring flex items-center gap-2 rounded-md text-sm font-bold tracking-tight outline-none focus-visible:ring-1"
    >
      <BrandMark />
      {appName}
    </Link>
  );
}
