import { useState, type ReactNode } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowLeftRight, BookOpenCheck, Bot, FileSignature, FileSpreadsheet, History, Inbox, MessageSquare, ScrollText, Sparkles, Star, X,
} from "lucide-react";
import { api } from "@/lib/api";
import type { Meta } from "@/lib/types";
import { day } from "@/lib/format";
import { ROLE_LABEL, ROLE_OF, useUser } from "@/lib/user";
import { Badge, Button, cn } from "@/components/ui";

const NAV = [
  { to: "/chat", label: "Chat", icon: MessageSquare, hint: "Raise a PR" },
  { to: "/inbox", label: "Inbox", icon: Inbox, hint: "Buyer workspace" },
  { to: "/batches", label: "Batches", icon: FileSpreadsheet, hint: "Upload & export" },
  { to: "/policy", label: "Policy", icon: ScrollText, hint: "Versions & amendments" },
  { to: "/contracts", label: "Contracts", icon: FileSignature, hint: "Register & PDFs" },
  { to: "/suppliers", label: "Suppliers", icon: Star, hint: "Preferred lists" },
  { to: "/compare", label: "Runs compare", icon: ArrowLeftRight, hint: "Run 1 vs Run 2" },
  { to: "/audit", label: "Audit", icon: History, hint: "Who did what" },
];

export function useMeta() {
  return useQuery({ queryKey: ["meta"], queryFn: () => api.get<Meta>("/api/meta"), staleTime: 15_000 });
}

export function Layout({ children }: { children: ReactNode }) {
  const { user, role, setUser } = useUser();
  const meta = useMeta();
  const loc = useLocation();
  return (
    <div className="flex h-full">
      <aside className="flex w-56 shrink-0 flex-col border-r border-border bg-white">
        <Link to="/" className="flex items-center gap-2 px-4 py-4">
          <img src="/favicon.svg" alt="" className="h-7 w-7" />
          <div>
            <div className="text-sm font-semibold leading-tight">Corvo Procure</div>
            <div className="text-[11px] text-muted-foreground">PR → PO, by policy</div>
          </div>
        </Link>
        <nav className="flex-1 space-y-0.5 px-2">
          {NAV.map(({ to, label, icon: Icon, hint }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                cn(
                  "group flex items-center gap-3 rounded-md px-3 py-2 text-sm",
                  isActive || loc.pathname.startsWith(to) ? "bg-primary/10 font-medium text-primary" : "text-foreground/80 hover:bg-muted",
                )
              }
            >
              <Icon className="h-4 w-4" />
              <span className="flex-1">{label}</span>
              <span className="hidden text-[10px] text-muted-foreground group-hover:inline">{hint}</span>
            </NavLink>
          ))}
        </nav>
        <div className="border-t border-border p-3 text-[11px] text-muted-foreground">
          <a href="/docs" target="_blank" rel="noreferrer" className="flex items-center gap-1 hover:text-foreground">
            <BookOpenCheck className="h-3.5 w-3.5" /> API docs (OpenAPI)
          </a>
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center justify-between gap-3 border-b border-border bg-white px-5">
          <div className="flex items-center gap-2 text-sm">
            {meta.data && (
              <>
                <Link to="/policy">
                  <Badge className="bg-indigo-50 text-indigo-700 ring-indigo-600/20" title="Latest approved policy version">
                    <ScrollText className="h-3 w-3" /> Policy v{meta.data.active_policy} · from {day(meta.data.effective_from)}
                  </Badge>
                </Link>
                <Badge
                  className={meta.data.llm_available ? "bg-emerald-50 text-emerald-700 ring-emerald-600/20" : "bg-slate-50 text-slate-600 ring-slate-500/20"}
                  title={meta.data.llm_available ? "An LLM reads amendments and chat" : "No LLM key: deterministic readers and the structured editor are used"}
                >
                  <Bot className="h-3 w-3" /> AI {meta.data.llm_available ? "on" : "off (deterministic)"}
                </Badge>
                <span className="hidden text-xs text-muted-foreground md:inline">Today {day(meta.data.today)} · IST</span>
              </>
            )}
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground">Acting as</span>
            <div className="inline-flex rounded-md border border-border bg-muted p-0.5" role="radiogroup" aria-label="Role switcher">
              {Object.keys(ROLE_OF).map((name) => (
                <button
                  key={name}
                  type="button"
                  role="radio"
                  aria-checked={user === name}
                  onClick={() => setUser(name)}
                  className={cn(
                    "rounded px-2.5 py-1 text-xs font-medium",
                    user === name ? "bg-white shadow-sm" : "text-muted-foreground hover:text-foreground",
                  )}
                >
                  {name} <span className="text-muted-foreground">· {ROLE_LABEL[ROLE_OF[name]]}</span>
                </button>
              ))}
            </div>
            <span className="sr-only">Current role {ROLE_LABEL[role]}</span>
          </div>
        </header>
        <main className="min-h-0 flex-1 overflow-y-auto px-6 py-5 scrollbar-thin">{children}</main>
      </div>
    </div>
  );
}

export function WelcomePanel() {
  const [open, setOpen] = useState(() => {
    try {
      return localStorage.getItem("corvo.welcome") !== "done";
    } catch {
      return true;
    }
  });
  const { setUser } = useUser();
  if (!open) return null;
  const close = () => {
    setOpen(false);
    try {
      localStorage.setItem("corvo.welcome", "done");
    } catch {
      /* ignore */
    }
  };
  const steps = [
    { n: 1, title: "Raise a PR in chat", text: "As Asha (requester), type “need 200 nitrile gloves for Chakan by next Friday”.", to: "/chat", user: "Asha" },
    { n: 2, title: "Review the inbox", text: "As Rahul (buyer), open the sample batch: every decision explains its rule, clause and contract or PO.", to: "/inbox", user: "Rahul" },
    { n: 3, title: "Try a policy amendment", text: "As Meera (procurement admin), propose a change, see its impact on the batch, approve it and re-run.", to: "/policy", user: "Meera" },
  ];
  return (
    <div className="mb-6 rounded-lg border border-primary/20 bg-gradient-to-r from-primary/5 to-white p-4">
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-2 text-sm font-semibold"><Sparkles className="h-4 w-4 text-primary" /> Welcome to Corvo Procure — a 3-minute tour</div>
        <button onClick={close} className="rounded p-1 text-muted-foreground hover:bg-muted" aria-label="Dismiss"><X className="h-4 w-4" /></button>
      </div>
      <div className="mt-3 grid gap-3 md:grid-cols-3">
        {steps.map((s) => (
          <Link key={s.n} to={s.to} onClick={() => setUser(s.user)} className="rounded-md border border-border bg-white p-3 hover:border-primary/50">
            <div className="text-xs font-medium text-primary">Step {s.n}</div>
            <div className="text-sm font-medium">{s.title}</div>
            <div className="mt-1 text-xs text-muted-foreground">{s.text}</div>
          </Link>
        ))}
      </div>
      <div className="mt-3 text-right">
        <Button size="sm" variant="secondary" onClick={close}>Got it</Button>
      </div>
    </div>
  );
}
