import { Sparkles } from "lucide-react";

import { APP_NAME } from "@/lib/constants";

const HIGHLIGHTS = [
  "Agents built in a UI, versioned on publish",
  "Knowledge, skills and tools switched on per agent",
  "Budgets, approvals and an audit trail on every run",
];

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="bg-background text-foreground min-h-screen lg:grid lg:grid-cols-[1.1fr_minmax(0,560px)]">
      <main id="main" className="theme-light bg-background text-foreground relative flex flex-col">
        <header className="flex h-16 items-center px-6 sm:px-10">
          {/* Not a link: the root redirects straight back here, so a brand
              mark that navigates would be a no-op. */}
          <span className="text-foreground inline-flex items-center gap-2 text-base font-bold tracking-tight">
            <span aria-hidden className="bg-brand inline-block h-2.5 w-2.5 rounded-full" />
            {APP_NAME}
          </span>
        </header>

        <div className="flex flex-1 items-center justify-center px-6 py-10 sm:px-10">
          <div className="w-full max-w-md">{children}</div>
        </div>

        <footer className="text-foreground/50 px-6 py-6 font-mono text-[11px] tracking-wider uppercase sm:px-10">
          © {new Date().getFullYear()} {APP_NAME}
        </footer>
      </main>

      <aside className="hidden p-5 lg:block lg:p-6">
        <div className="theme-dark bg-background text-foreground border-foreground/10 relative flex h-full flex-col justify-between overflow-hidden rounded-3xl border p-10 shadow-2xl lg:p-12">
          <div aria-hidden className="pointer-events-none absolute inset-0">
            <div className="bg-grid absolute inset-0 opacity-[0.55]" />
            <div className="bg-brand/[0.28] absolute -top-32 -right-20 h-[460px] w-[460px] rounded-full blur-[120px]" />
            <div className="bg-brand/[0.12] absolute -bottom-20 -left-10 h-[320px] w-[420px] rounded-full blur-[140px]" />
          </div>

          <div className="relative z-10">
            <span className="eyebrow-badge inline-flex items-center gap-2">
              <Sparkles className="h-3 w-3" aria-hidden />
              Self-hosted, open source
            </span>
          </div>

          <div className="relative z-10 max-w-[28rem]">
            <h2 className="text-display-lg text-foreground mb-6 leading-[1.05] [&_em]:font-normal [&_em]:italic">
              The operating system for <em>your company&apos;s</em> AI agents.
            </h2>
            <p className="text-foreground/65 max-w-md text-base leading-relaxed">
              An agent here is data, not code - instructions, a model, a set of capabilities. It
              runs the same way on web chat, the HTTP API and Slack, on your infrastructure and
              against your keys.
            </p>

            <ul className="mt-10 space-y-3">
              {HIGHLIGHTS.map((line) => (
                <li key={line} className="text-foreground/85 flex items-center gap-3 text-sm">
                  <span aria-hidden className="bg-brand h-1.5 w-1.5 shrink-0 rounded-full" />
                  {line}
                </li>
              ))}
            </ul>
          </div>

          <p className="text-foreground/55 relative z-10 max-w-md font-mono text-[11px] leading-relaxed tracking-wider uppercase">
            Apache-2.0 · your infrastructure · your keys
          </p>
        </div>
      </aside>
    </div>
  );
}
