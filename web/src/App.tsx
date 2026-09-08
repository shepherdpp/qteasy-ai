import React, { useMemo, useState } from "react";
import type { WorkbenchState } from "./types";

export function App({ initial }: { initial?: WorkbenchState }) {
  const [mode, setMode] = useState<"ask" | "plan" | "agent">("plan");
  const state = initial;
  const modeLabel = useMemo(() => mode.toUpperCase(), [mode]);
  return (
    <div>
      <header>
        <strong>qteasy-ai Workbench</strong>
        <span data-testid="mode-badge">Mode: {modeLabel}</span>
        <button onClick={() => setMode("ask")}>Ask</button>
        <button onClick={() => setMode("plan")}>Plan</button>
        <button onClick={() => setMode("agent")}>Agent</button>
      </header>
      <main className="layout">
        <section id="chat-col">
          <h2>Chat</h2>
          {(state?.messages || []).map((msg, idx) => (
            <div key={idx}>{msg.kind}: {msg.text}</div>
          ))}
        </section>
        <section id="artifact-col">
          <h2>Artifacts</h2>
        </section>
        <section id="sidebar-col">
          <h2>State</h2>
        </section>
      </main>
    </div>
  );
}
