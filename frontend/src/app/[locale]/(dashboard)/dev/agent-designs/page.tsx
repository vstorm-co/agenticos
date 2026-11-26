import { notFound } from "next/navigation";

import { AgentDesignPreview } from "./preview";

export default async function AgentDesignPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  if (process.env.NODE_ENV === "production") notFound();
  const query = await searchParams;
  const variant =
    query.variant === "directory" || query.variant === "compact" ? query.variant : "profile";
  return <AgentDesignPreview variant={variant} build={query.section === "build"} />;
}
