import { MyMemory } from "@/components/memory/my-memory";

/** The caller's own memory; organization roles do not gate access to it. */
export default function MemoryPage() {
  return (
    <div className="flex min-h-0 flex-1 flex-col pb-4">
      <MyMemory />
    </div>
  );
}
