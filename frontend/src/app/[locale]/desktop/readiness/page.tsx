import { ReadinessScreen } from "@/components/desktop/readiness-screen";
/** Reachable from connection setup and native repair actions before sign-in. */
export default async function DesktopReadinessPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  return (
    <ReadinessScreen
      repair={typeof params.repair === "string" ? params.repair : null}
      connection={params.connection === "1"}
    />
  );
}
