"use client";

import { useState } from "react";

import { ConversationVisualsProvider, TurnVisuals } from "@/components/chat/visual-panel";
import { VisualWorkspaceSlot } from "@/components/chat/chat-workspace-context";
import { ThemeToggle } from "@/components/theme";
import type { ChatMessage, ToolCall } from "@/types";

const TITLE = "Od pytania do odpowiedzi";
const SVG = `<svg width="800" height="380" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 380" role="img" aria-label="Pytanie użytkownika, praca agenta i gotowa odpowiedź">
      <defs><marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M0 0L10 5L0 10" fill="none" stroke="#a5b2b2" stroke-width="1.6"/></marker></defs>
      <rect width="800" height="380" fill="#fff"/>
      <text x="44" y="48" font-family="Arial,sans-serif" fill="#84918f" font-size="11" letter-spacing="1.5">OD PYTANIA DO ODPOWIEDZI</text>
      <text x="44" y="86" font-family="Arial,sans-serif" fill="#263d3a" font-size="28" font-weight="600">Jeden przepływ. Czytelny wynik.</text>
      <path d="M251 208H286M514 208H549" stroke="#a5b2b2" stroke-width="1.5" marker-end="url(#arrow)"/>
      <rect x="44" y="143" width="207" height="136" rx="12" fill="#f6f8f8" stroke="#e0e7e6"/>
      <circle cx="72" cy="173" r="13" fill="#e7edec"/><text x="72" y="177" text-anchor="middle" font-family="Arial,sans-serif" font-size="11" fill="#536c66">1</text>
      <text x="65" y="218" font-family="Arial,sans-serif" fill="#263d3a" font-size="19" font-weight="600">Pytanie</text>
      <text x="65" y="246" font-family="Arial,sans-serif" fill="#738780" font-size="13">Cel i potrzebny kontekst</text>
      <rect x="292" y="143" width="222" height="136" rx="12" fill="#e9f4ef" stroke="#c9e4d8"/>
      <circle cx="320" cy="173" r="13" fill="#c9e4d8"/><text x="320" y="177" text-anchor="middle" font-family="Arial,sans-serif" font-size="11" fill="#2e6855">2</text>
      <text x="313" y="218" font-family="Arial,sans-serif" fill="#264e40" font-size="19" font-weight="600">Praca agenta</text>
      <text x="313" y="246" font-family="Arial,sans-serif" fill="#5b7d6e" font-size="13">Wiedza, narzędzia i weryfikacja</text>
      <rect x="555" y="143" width="201" height="136" rx="12" fill="#f6f8f8" stroke="#e0e7e6"/>
      <circle cx="583" cy="173" r="13" fill="#e7edec"/><text x="583" y="177" text-anchor="middle" font-family="Arial,sans-serif" font-size="11" fill="#536c66">3</text>
      <text x="576" y="218" font-family="Arial,sans-serif" fill="#263d3a" font-size="19" font-weight="600">Odpowiedź</text>
      <text x="576" y="246" font-family="Arial,sans-serif" fill="#738780" font-size="13">Wynik gotowy do użycia</text>
      <path d="M44 322H756" stroke="#edf0ef"/>
      <text x="44" y="348" font-family="Arial,sans-serif" fill="#84918f" font-size="11">DIAGRAM PRZEPŁYWU</text><text x="756" y="348" text-anchor="end" font-family="Arial,sans-serif" fill="#84918f" font-size="11">3 KROKI</text>
    </svg>`;

const HTML = `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>
*{box-sizing:border-box}html{color-scheme:light dark}body{margin:0;padding:24px;font:14px/1.5 system-ui,sans-serif;color:light-dark(#263d3a,#e3eeea);background:light-dark(#fff,#171e1c)}h1{font-size:24px;letter-spacing:-.03em;line-height:1.2;margin:8px 0 10px}p{color:light-dark(#738780,#9eafa7);margin:0 0 26px}label{display:flex;justify-content:space-between;gap:12px}input[type=range]{width:100%;accent-color:#439773;margin:18px 0}input[type=text]{width:100%;padding:10px 12px;border-radius:8px;border:1px solid light-dark(#d6e2dc,#3d4d44);background:transparent;color:inherit;font:inherit;margin-top:8px}.total{font-size:40px;line-height:1.2;font-weight:650;margin-top:30px;font-variant-numeric:tabular-nums}.small{font-size:12px;color:light-dark(#738780,#9eafa7)}.track{height:12px;background:light-dark(#e9f0ed,#304238);border-radius:8px;overflow:hidden;margin:18px 0 28px}.bar{height:100%;width:40%;background:#439773;border-radius:8px}.note{margin-top:26px;padding-top:18px;border-top:1px solid light-dark(#e0e7e3,#304238)}
</style></head><body><div class="small">HTML + JavaScript · illustrative data</div><h1>Subscription calculator</h1><p>Change the slider and add a note. Both should survive every view change.</p><label for="units">Monthly subscriptions <output id="count">400</output></label><input id="units" type="range" min="100" max="1000" step="10" value="400"><div class="small">Illustrative price: €20 per month</div><div id="revenue" class="total">€8,000</div><div class="small">Illustrative monthly revenue</div><div class="track"><div id="bar" class="bar"></div></div><label for="note">Your scenario note</label><input id="note" type="text" placeholder="e.g. expansion scenario"><div class="note small">The calculation runs in this page. No network calls.</div><script>
(function(){const units=document.getElementById('units');function render(){const n=Number(units.value);document.getElementById('count').textContent=String(n);document.getElementById('revenue').textContent=new Intl.NumberFormat('en-IE',{style:'currency',currency:'EUR',maximumFractionDigits:0}).format(n*20);document.getElementById('bar').style.width=(n/10)+'%';}units.addEventListener('input',render);render();})();
</script></body></html>`;

const calls: ToolCall[] = [
  {
    id: "preview-html",
    name: "draw",
    args: { title: "Subscription calculator", kind: "html", height: 520, content: HTML },
    status: "completed",
    result: "Drew Subscription calculator",
  },
  {
    id: "preview-svg",
    name: "draw",
    args: { title: TITLE, kind: "svg", height: 380, content: SVG },
    status: "completed",
    result: "Drew flow",
  },
];
const messages: ChatMessage[] = [
  { id: "preview-reply", role: "assistant", content: "", timestamp: new Date(0), toolCalls: calls },
];

/** A local conversation using the production renderer, workspace and export controls. */
export function VisualWorkspacePreview() {
  const [draft, setDraft] = useState("");
  return (
    <ConversationVisualsProvider messages={messages} conversationId={null}>
      <main id="main" className="@container/visual-layout flex h-dvh min-h-0 overflow-hidden">
        <div className="flex min-w-0 flex-1 flex-col">
          <header className="flex shrink-0 items-center justify-between gap-4 border-b px-5 py-4">
            <div>
              <p className="text-muted-foreground text-xs">Visuals · podgląd lokalny</p>
              <h1 className="mt-1 text-lg font-semibold">Strona HTML obok rozmowy</h1>
            </div>
            <ThemeToggle />
          </header>
          <div data-chat-scroller className="min-h-0 flex-1 overflow-y-auto px-5 py-6">
            <div className="mx-auto max-w-3xl">
              <p className="text-muted-foreground mb-6 text-sm">
                Zmień suwak i wpisz notatkę. Otwórz panel boczny, przełącz Kod / Podgląd, a
                następnie pełny ekran. Stan strony powinien pozostać taki sam.
              </p>
              <TurnVisuals calls={calls} />
            </div>
          </div>
          <footer className="shrink-0 border-t p-4">
            <input
              aria-label="Wiadomość testowa"
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              placeholder="Rozmowa pozostaje dostępna obok panelu…"
              className="border-input bg-background w-full rounded-xl border px-4 py-3 text-sm"
            />
          </footer>
        </div>
        <VisualWorkspaceSlot />
      </main>
    </ConversationVisualsProvider>
  );
}
