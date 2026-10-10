import { ConsentScreen } from "@/components/oauth/consent-screen";

/**
 * Where an MCP client's `/authorize` sends a person to consent (#2059). Signed-in
 * and full-window, like an artifact: nothing of the console around a decision
 * that is about letting something else act as you.
 */
export default async function ConsentPage({
  searchParams,
}: {
  searchParams: Promise<{ request?: string }>;
}) {
  const { request } = await searchParams;
  return (
    <div className="flex flex-1 items-center justify-center p-4">
      <ConsentScreen requestId={request ?? ""} />
    </div>
  );
}
