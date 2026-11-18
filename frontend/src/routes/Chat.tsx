import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { Bot, CheckCircle2, ClipboardList, RotateCcw, Send, User as UserIcon } from "lucide-react";
import { api } from "@/lib/api";
import type { ChatMessage, ChatSession, ConfirmCard } from "@/lib/types";
import { day, inr, qty } from "@/lib/format";
import { useUser } from "@/lib/user";
import { Badge, Button, Card, CardBody, CardHeader, CardTitle, ErrorBox, Input, Notice, RouteBadge, cn } from "@/components/ui";

function md(text: string) {
  return text.split("\n").map((line, i) => (
    <p key={i} className={i ? "mt-1" : ""}>
      {line.split(/(\*\*[^*]+\*\*)/g).map((part, j) => (part.startsWith("**") ? <b key={j}>{part.slice(2, -2)}</b> : <span key={j}>{part}</span>))}
    </p>
  ));
}

export default function ChatPage() {
  const { user, role } = useUser();
  const [session, setSession] = useState<ChatSession | null>(null);
  const [text, setText] = useState("");
  const endRef = useRef<HTMLDivElement>(null);
  const start = useMutation({ mutationFn: () => api.post<ChatSession>("/api/chat/sessions"), onSuccess: setSession });
  const send = useMutation({
    mutationFn: (body: { text: string; value?: string }) => api.post<ChatSession>(`/api/chat/sessions/${session!.id}/messages`, body),
    onSuccess: (s) => setSession(s),
  });
  useEffect(() => {
    if (!session || session.user !== user) start.mutate();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user]);
  useEffect(() => {
    // braces on purpose: an effect must return nothing or a cleanup function, never scrollIntoView's result
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [session?.messages.length, send.isPending]);

  const pending = send.isPending ? send.variables : null;
  const messages: ChatMessage[] = [...(session?.messages ?? [])];
  if (pending) messages.push({ id: -1, role: "user", content: pending.text || pending.value || "", meta: {}, at: "" });
  const last = session?.messages.filter((m) => m.role === "assistant").slice(-1)[0];
  const submit = (body: { text: string; value?: string }) => {
    if (!session || send.isPending || !(body.text || body.value)) return;
    send.mutate(body);
    setText("");
  };

  return (
    <div className="mx-auto grid h-full max-w-6xl gap-4 lg:grid-cols-[1fr_300px]">
      <Card className="flex min-h-[70vh] flex-col">
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><Bot className="h-4 w-4 text-primary" /> Raise a purchase request</CardTitle>
          <Button size="sm" variant="ghost" onClick={() => start.mutate()}><RotateCcw className="h-3.5 w-3.5" /> New chat</Button>
        </CardHeader>
        {role === "PROCUREMENT_ADMIN" && (
          <Notice className="m-3 mb-0">Want to change the policy instead? <Link to="/policy/amendments/new" className="font-medium underline">Describe a policy change</Link>.</Notice>
        )}
        <div className="flex-1 space-y-3 overflow-y-auto p-4 scrollbar-thin" aria-live="polite">
          {start.isPending && !session && <div className="text-sm text-muted-foreground">Starting…</div>}
          {messages.map((m) => (
            <div key={m.id} className={cn("flex gap-2", m.role === "user" && "flex-row-reverse")}>
              <div className={cn("mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full", m.role === "user" ? "bg-slate-200" : "bg-primary/10 text-primary")}>
                {m.role === "user" ? <UserIcon className="h-4 w-4" /> : <Bot className="h-4 w-4" />}
              </div>
              <div className={cn("max-w-[80%] space-y-2", m.role === "user" && "items-end text-right")}>
                <div className={cn("inline-block rounded-2xl px-3.5 py-2 text-sm", m.role === "user" ? "rounded-tr-sm bg-primary text-primary-foreground" : "rounded-tl-sm bg-muted")}>
                  {md(m.content)}
                </div>
                {m.meta?.card && <ConfirmCardView card={m.meta.card} />}
                {m.meta?.created && (
                  <div className="flex items-center gap-2 text-xs"><CheckCircle2 className="h-4 w-4 text-emerald-600" />
                    <Link to={`/inbox?run=${m.meta.created.run_id}`} className="text-primary hover:underline">Open in the buyer inbox</Link>
                  </div>
                )}
                {m.meta?.chips && m === last && (
                  <div className="flex flex-wrap gap-1.5">
                    {m.meta.chips.map((c) => (
                      <button key={c.value + c.label} disabled={send.isPending} onClick={() => submit({ text: "", value: c.value })}
                        className="rounded-full border border-primary/40 bg-white px-3 py-1 text-xs font-medium text-primary hover:bg-primary/5 disabled:opacity-50">
                        {c.label}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ))}
          {send.isPending && (
            <div className="flex gap-2"><div className="flex h-7 w-7 items-center justify-center rounded-full bg-primary/10 text-primary"><Bot className="h-4 w-4" /></div>
              <div className="rounded-2xl rounded-tl-sm bg-muted px-4 py-3"><span className="inline-flex gap-1">{[0, 1, 2].map((i) => <span key={i} className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted-foreground" style={{ animationDelay: `${i * 120}ms` }} />)}</span></div>
            </div>
          )}
          {send.isError && <ErrorBox error={send.error} />}
          <div ref={endRef} />
        </div>
        <form className="flex gap-2 border-t border-border p-3" onSubmit={(e) => { e.preventDefault(); submit({ text }); }}>
          <Input value={text} onChange={(e) => setText(e.target.value)} placeholder="e.g. need 200 nitrile gloves for Chakan by next Friday" disabled={!session} autoFocus />
          <Button type="submit" disabled={!text.trim() || send.isPending}><Send className="h-4 w-4" /> Send</Button>
        </form>
      </Card>
      <DraftPanel session={session} />
    </div>
  );
}

function ConfirmCardView({ card }: { card: ConfirmCard }) {
  return (
    <div className="rounded-lg border border-border bg-white p-3 text-left text-sm shadow-sm">
      <div className="mb-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
        <span>Plant <b className="text-foreground">{card.plant_name} ({card.plant})</b></span>
        <span>Need by <b className="text-foreground">{card.need_by_label}</b></span>
        <span>Urgency <b className={card.urgency === "Emergency" ? "text-rose-700" : "text-foreground"}>{card.urgency}</b></span>
        <span>Requester <b className="text-foreground">{card.requester}</b></span>
      </div>
      {card.lines.map((l, i) => (
        <div key={i} className="border-t border-border py-2 first:border-0">
          <div className="flex items-start justify-between gap-2">
            <div><b>{l.is_new ? "New item" : l.item_code}</b> {l.description}</div>
            <div className="num whitespace-nowrap">{qty(l.qty)} {l.uom}</div>
          </div>
          {l.is_new && l.est_price && <div className="text-xs text-muted-foreground">Estimated {inr(l.est_price)} per unit</div>}
          {l.preview?.route && (
            <div className="mt-1 flex items-start gap-2 rounded-md bg-muted/60 p-2 text-xs">
              <RouteBadge route={l.preview.route} />
              <span>{l.preview_text}</span>
            </div>
          )}
        </div>
      ))}
      <div className="mt-1 text-[11px] text-muted-foreground">Live preview from the policy engine; the buyer confirms the final decision.</div>
    </div>
  );
}

function DraftPanel({ session }: { session: ChatSession | null }) {
  const d = session?.draft;
  return (
    <Card className="h-fit">
      <CardHeader><CardTitle className="flex items-center gap-2"><ClipboardList className="h-4 w-4" /> PR draft</CardTitle>{d?.pr_no && <Badge className="bg-emerald-50 text-emerald-700 ring-emerald-600/20">{d.pr_no}</Badge>}</CardHeader>
      <CardBody className="space-y-3 text-sm">
        {!d || d.lines.length === 0 ? <div className="text-muted-foreground">Items you mention appear here.</div> : d.lines.map((l, i) => (
          <div key={i} className="rounded-md border border-border p-2">
            <div className="font-medium">{l.is_new ? "New item" : l.item_code ?? "matching…"}</div>
            <div className="text-xs text-muted-foreground">{l.description}</div>
            <div className="num text-xs">{l.qty ? `${qty(l.qty)} ${l.uom ?? ""}` : "quantity?"}{l.est_price && ` · est. ${inr(l.est_price)}`}</div>
          </div>
        ))}
        <dl className="grid grid-cols-[80px_1fr] gap-y-1 text-xs">
          <dt className="text-muted-foreground">Plant</dt><dd>{d?.plant ?? "—"}</dd>
          <dt className="text-muted-foreground">Need by</dt><dd>{d?.need_by ? day(d.need_by) : "—"}</dd>
          <dt className="text-muted-foreground">Urgency</dt><dd>{d?.urgency ?? "—"}</dd>
          <dt className="text-muted-foreground">Status</dt><dd>{d?.stage === "created" ? "PR raised" : d?.stage === "confirm" ? "waiting for your confirmation" : "collecting details"}</dd>
        </dl>
        <div className="text-[11px] text-muted-foreground">Items always come from the item master; if nothing matches, it becomes a new-item sourcing request.</div>
      </CardBody>
    </Card>
  );
}
