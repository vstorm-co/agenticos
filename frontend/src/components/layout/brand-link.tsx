"use client";

import Link from "next/link";
import { Sparkles } from "lucide-react";

import { APP_NAME, ROUTES } from "@/lib/constants";

/**
 * The product's name, as a link home.
 *
 * Shared by the two places that are ever the top-left of the screen: the head
 * of the column above `md`, and the mobile bar below it. One of them is always
 * on screen and never both.
 */
export function BrandLink() {
  return (
    <Link
      href={ROUTES.DASHBOARD}
      className="focus-visible:ring-ring flex items-center gap-2 rounded-md text-sm font-bold tracking-tight outline-none focus-visible:ring-1"
    >
      <span
        aria-hidden
        className="bg-foreground text-background inline-flex h-6 w-6 items-center justify-center rounded-md"
      >
        <Sparkles className="h-3.5 w-3.5" />
      </span>
      {APP_NAME}
    </Link>
  );
}
