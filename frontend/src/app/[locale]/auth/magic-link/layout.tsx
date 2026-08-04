import type { Metadata, Viewport } from "next";
import { getTranslations } from "next-intl/server";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("pages.meta");
  return {
    title: t("magicLinkTitle"),
    robots: { index: false, follow: false },
  };
}

export const viewport: Viewport = {
  themeColor: "#0E0E0C",
};

export default function MagicLinkVerifyLayout({ children }: { children: React.ReactNode }) {
  return children;
}
