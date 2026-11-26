import { MyMemory } from "@/components/memory/my-memory";

/** The caller's own memory; organization roles do not gate access to it. */
export default async function MemoryPage({
  searchParams,
}: {
  searchParams: Promise<{ object?: string | string[]; library?: string | string[] }>;
}) {
  const params = await searchParams;
  const object =
    typeof params.object === "string" &&
    /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(params.object)
      ? params.object
      : undefined;
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <MyMemory
        initialObject={object}
        initialLibrary={params.library === "organization" ? "organization" : "personal"}
      />
    </div>
  );
}
