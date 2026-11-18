import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Bot, CheckCircle2, HelpCircle, Pencil, Quote, XCircle } from "lucide-react";
import { api } from "@/lib/api";
import type { Amendment } from "@/lib/types";
import { day, dayTime, inr } from "@/lib/format";
import { useUser } from "@/lib/user";
import { OpsEditor, type Op } from "@/components/OpsEditor";
import {
  Badge, Button, Card, CardBody, CardHeader, CardTitle, Dialog, DialogContent, DialogTrigger, ErrorBox, Input, Notice, PageHeader,
  RouteBadge, Spinner, Stat, StatusBadge, Textarea,
} from "@/components/ui";

function highlight(text: string, quotes: string[], active: number | null) {
  type Seg = { s: number; e: number; i: number };
  const segs: Seg[] = [];
  const low = text.toLowerCase();
  quotes.forEach((q, i) => {
    const needle = q.trim().toLowerCase();
    if (needle.length < 4) return;
    const at = low.indexOf(needle);
    if (at >= 0) segs.push({ s: at, e: at + needle.length, i });
  });
  segs.sort((a, b) => a.s - b.s);
  const out: React.ReactNode[] = [];
  let pos = 0;
  segs.forEach((g, k) => {
    if (g.s < pos) return;
    out.push(<span key={`t${k}`}>{text.slice(pos, g.s)}</span>);
    out.push(
      <mark key={`m${k}`} className={`rounded px-0.5 ${active === g.i ? "bg-amber-300" : "bg-amber-100"}`}>
        {text.slice(g.s, g.e)}<sup className="ml-0.5 text-[10px] font-semibold text-amber-800">{g.i + 1}</sup>
      </mark>,
    );
    pos = g.e;
  });
  out.push(<span key="end">{text.slice(pos)}</span>);
  return out;
}

export default function AmendmentPage() {
  const { id } = useParams();
  const nav = useNavigate();
  const qc = useQueryClient();
  const { role } = useUser();
  const [active, setActive] = useState<number | null>(null);
  const [editing, setEditing] = useState(false);
  const [draftOps, setDraftOps] = useState<Op[]>([]);
  const [eff, setEff] = useState("");
  const [comment, setComment] = useState("");
  const a = useQuery({ queryKey: ["amendment", id], queryFn: () => api.get<Amendment>(`/api/policy/amendments/${id}`) });

  const refresh = (data: Amendment) => {
    qc.setQueryData(["amendment", id], data);
    qc.invalidateQueries({ queryKey: ["amendments"] });
  };
  const update = useMutation({
    mutationFn: (body: { ops: Op[]; effective_from?: string | null }) => api.put<Amendment>(`/api/policy/amendments/${id}`, body),
    onSuccess: (d) => { refresh(d); setEditing(false); },
  });
  const approve = useMutation({
    mutationFn: () => api.post<Amendment>(`/api/policy/amendments/${id}/approve`, { comment }),
    onSuccess: (d) => { refresh(d); qc.invalidateQueries(); },
  });
  const reject = useMutation({
    mutationFn: () => api.post<Amendment>(`/api/policy/amendments/${id}/reject`, { comment }),
    onSuccess: (d) => refresh(d),
  });

  const ops = useMemo(() => (a.data?.ops ?? []).filter((o) => o.op !== "set_effective_from"), [a.data]);
  if (a.isLoading) return <Spinner />;
  if (a.isError) return <ErrorBox error={a.error} />;
  const am = a.data!;
  const quotes = am.summary.map((s) => s.source_quote || "");
  const decided = am.status === "APPROVED" || am.status === "REJECTED";
  const ai = am.ai_meta as { provider?: string; model?: string; latency_ms?: number; repaired?: boolean; quote_warnings?: string[]; llm_error?: string };
  const impact = am.impact ?? {};

  return (
    <div className="mx-auto max-w-[1400px]">
      <PageHeader
        title={am.title}
        subtitle={<span className="flex flex-wrap items-center gap-2">
          <StatusBadge status={am.status} /> Amendment #{am.id} · v{am.base_version} → <b>v{am.proposed_version}</b> ·
          {am.source_kind === "DOC" ? ` document ${am.source_filename}` : am.source_kind === "CHAT" ? " described in words" : " structured editor"} · {am.created_by}, {dayTime(am.created_at)}
          {ai?.provider && <Badge className="bg-slate-50 text-slate-600 ring-slate-500/20"><Bot className="h-3 w-3" /> read by {ai.provider}{ai.model ? ` (${ai.model})` : ""}{ai.latency_ms ? ` · ${(ai.latency_ms / 1000).toFixed(1)} s` : ""}{ai.repaired ? " · repaired once" : ""}</Badge>}
        </span>}
        actions={!decided && <Button variant="secondary" onClick={() => { setDraftOps(ops); setEditing(true); }}><Pencil className="h-4 w-4" /> Edit in structured editor</Button>}
      />

      {am.status === "APPROVED" && (
        <Notice tone="ok" className="mb-4">
          Approved by {am.decided_by} · v{am.proposed_version} is active from <b>{day(am.effective_from)}</b>. <Link to="/batches" className="font-medium underline">Re-run the batch</Link> to apply it (Run 2), then <Link to="/compare" className="font-medium underline">compare runs</Link>.
        </Notice>
      )}
      {am.errors.length > 0 && <div className="mb-4"><ErrorBox error={new Error("These changes cannot be applied yet")} title="Validation errors" /><ul className="mt-2 list-disc pl-6 text-sm text-red-700">{am.errors.map((e) => <li key={e}>{e}</li>)}</ul></div>}

      {editing && (
        <Card className="mb-4 border-primary/40">
          <CardHeader><CardTitle>Structured editor</CardTitle><div className="flex gap-2"><Button variant="ghost" size="sm" onClick={() => setEditing(false)}>Cancel</Button><Button size="sm" loading={update.isPending} onClick={() => update.mutate({ ops: draftOps, effective_from: am.effective_from })}>Save & re-check</Button></div></CardHeader>
          <CardBody><OpsEditor ops={draftOps} onChange={setDraftOps} />{update.isError && <ErrorBox error={update.error} />}</CardBody>
        </Card>
      )}

      <Card className="mb-4">
        <CardBody className="flex flex-wrap items-center gap-3">
          <div className="text-sm">Effective from <b className="text-base">{day(am.effective_from)}</b> <span className="text-muted-foreground">({am.effective_from})</span></div>
          {!decided && (
            <>
              <Input type="date" className="h-8 w-44" value={eff || am.effective_from || ""} onChange={(e) => setEff(e.target.value)} />
              <Button size="sm" variant="secondary" disabled={!eff || eff === am.effective_from} loading={update.isPending} onClick={() => update.mutate({ ops, effective_from: eff })}>Change date & recompute impact</Button>
            </>
          )}
          <span className="text-xs text-muted-foreground">Requirements dated on or after this date use v{am.proposed_version}; earlier ones keep v{am.base_version}.</span>
        </CardBody>
      </Card>

      {(am.questions.length > 0 || am.lint.length > 0 || (ai?.quote_warnings ?? []).length > 0) && (
        <div className="mb-4 grid gap-3 md:grid-cols-2">
          {am.questions.length > 0 && (
            <Notice tone="warn"><div className="mb-1 flex items-center gap-1 font-medium"><HelpCircle className="h-4 w-4" /> Questions for the approver</div>
              <ul className="list-disc pl-5">{am.questions.map((q) => <li key={q}>{q}</li>)}</ul></Notice>
          )}
          {(am.lint.length > 0 || (ai?.quote_warnings ?? []).length > 0) && (
            <Notice><div className="mb-1 flex items-center gap-1 font-medium"><AlertTriangle className="h-4 w-4" /> Checks</div>
              <ul className="list-disc pl-5">{[...am.lint, ...(ai?.quote_warnings ?? [])].map((q) => <li key={q}>{q}</li>)}</ul></Notice>
          )}
        </div>
      )}

      <div className="mb-4 grid gap-4 lg:grid-cols-3">
        <Card>
          <CardHeader><CardTitle className="flex items-center gap-1"><Quote className="h-4 w-4" /> Source</CardTitle></CardHeader>
          <CardBody className="max-h-[480px] overflow-auto whitespace-pre-wrap text-sm leading-relaxed">
            {am.source_text ? highlight(am.source_text, quotes, active) : <span className="text-muted-foreground">Entered in the structured editor.</span>}
          </CardBody>
        </Card>
        <Card>
          <CardHeader><CardTitle>Operations ({am.ops.length})</CardTitle></CardHeader>
          <CardBody className="max-h-[480px] space-y-2 overflow-auto">
            {am.ops.map((op, i) => (
              <div key={i} onMouseEnter={() => setActive(i)} onMouseLeave={() => setActive(null)}
                className={`rounded-md border p-2 text-xs ${active === i ? "border-amber-400 bg-amber-50" : "border-border"}`}>
                <div className="mb-1 flex items-center gap-2"><span className="font-semibold text-amber-800">{i + 1}</span><Badge className="bg-slate-50 text-slate-700 ring-slate-500/20">{String(op.op)}</Badge></div>
                <pre className="whitespace-pre-wrap break-all font-mono text-[11px] text-muted-foreground">{JSON.stringify(Object.fromEntries(Object.entries(op).filter(([k]) => k !== "op" && k !== "source_quote")), null, 1)}</pre>
              </div>
            ))}
          </CardBody>
        </Card>
        <Card>
          <CardHeader><CardTitle>What changes, in plain language</CardTitle></CardHeader>
          <CardBody className="max-h-[480px] space-y-2 overflow-auto">
            {am.summary.length === 0 && <div className="text-sm text-muted-foreground">No valid changes yet.</div>}
            {am.summary.map((s, i) => (
              <div key={i} onMouseEnter={() => setActive(i)} onMouseLeave={() => setActive(null)}
                className={`rounded-md border p-2 text-sm ${active === i ? "border-amber-400 bg-amber-50" : "border-border"}`}>
                <span className="mr-1 font-semibold text-amber-800">{i + 1}.</span>{s.text}
                {s.source_quote && <div className="mt-1 text-xs italic text-muted-foreground">“{s.source_quote}”</div>}
              </div>
            ))}
          </CardBody>
        </Card>
      </div>

      <Card className="mb-4">
        <CardHeader><CardTitle>Impact preview {impact.run_name && <span className="font-normal text-muted-foreground">— re-run of “{impact.run_name}” under the current versions vs with v{am.proposed_version}</span>}</CardTitle></CardHeader>
        <CardBody>
          {!impact.available ? <div className="text-sm text-muted-foreground">{impact.message ?? "Impact is computed once the changes are valid."}</div> : (
            <>
              {(impact.warnings ?? []).map((w) => <Notice key={w} tone="warn" className="mb-2">{w}</Notice>)}
              <div className="mb-3 grid grid-cols-2 gap-3 md:grid-cols-4">
                <Stat label="Lines that change" value={impact.summary?.lines_changed ?? 0} sub={`of ${impact.summary?.lines_compared ?? 0}`} />
                <Stat label="Requirements on/after date" value={impact.requirements_on_or_after_effective ?? 0} sub={`of ${impact.requirements ?? 0}`} />
                <Stat label="Grouping changes" value={impact.summary?.grouping_changes ?? 0} sub="clubbing / PO membership" />
                <Stat label="Route moves" value={Object.values(impact.summary?.route_moves ?? {}).reduce((a, b) => a + b, 0)} />
              </div>
              {Object.keys(impact.summary?.route_moves ?? {}).length > 0 && (
                <div className="mb-3 flex flex-wrap gap-2 text-sm">{Object.entries(impact.summary!.route_moves).map(([k, v]) => <Badge key={k} className="bg-indigo-50 text-indigo-700 ring-indigo-600/20">{k}: {v}</Badge>)}</div>
              )}
              {(impact.changed ?? []).length > 0 && (
                <div className="max-h-96 overflow-auto rounded-md border border-border">
                  <table className="w-full text-sm">
                    <thead className="sticky top-0 bg-muted text-xs text-muted-foreground"><tr><th className="px-2 py-1.5 text-left">PR line</th><th className="text-left">Route</th><th className="text-left">What changed</th><th className="text-left">New reason</th></tr></thead>
                    <tbody>
                      {impact.changed!.map((c) => (
                        <tr key={`${c.pr_no}/${c.pr_line}`} className="border-t border-border align-top">
                          <td className="whitespace-nowrap px-2 py-1.5 font-medium">{c.pr_no}/{c.pr_line}</td>
                          <td className="whitespace-nowrap py-1.5"><RouteBadge route={c.old_route} /> → <RouteBadge route={c.new_route} /></td>
                          <td className="py-1.5 text-xs">{Object.entries(c.changes).filter(([k]) => k !== "route").map(([k, [o, n]]) => <div key={k}><span className="text-muted-foreground">{k}:</span> {k === "group_value_inr" || k === "unit_price" ? `${inr(o)} → ${inr(n)}` : `${o || "—"} → ${n || "—"}`}</div>)}</td>
                          <td className="max-w-md py-1.5 pr-2 text-xs text-muted-foreground">{c.new_reason}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}
        </CardBody>
      </Card>

      {!decided && (
        <Card className="sticky bottom-0 z-10 border-primary/30 shadow-lg">
          <CardBody className="flex flex-wrap items-center gap-3">
            <Textarea className="h-10 flex-1" value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Approval note (optional)" />
            <Dialog>
              <DialogTrigger asChild><Button variant="secondary" disabled={role === "REQUESTER"}><XCircle className="h-4 w-4" /> Reject</Button></DialogTrigger>
              <DialogContent title="Reject this amendment?" description="The candidate version is discarded. The audit trail keeps the record.">
                <div className="flex justify-end"><Button variant="destructive" loading={reject.isPending} onClick={() => reject.mutate()}>Reject</Button></div>
              </DialogContent>
            </Dialog>
            <Button size="lg" variant="success" disabled={am.status !== "PROPOSED" || role === "REQUESTER"} loading={approve.isPending} onClick={() => approve.mutate()}>
              <CheckCircle2 className="h-4 w-4" /> Approve & activate from {day(am.effective_from)}
            </Button>
            {(approve.isError || reject.isError) && <div className="w-full"><ErrorBox error={approve.error ?? reject.error} /></div>}
            {role === "REQUESTER" && <div className="w-full text-xs text-muted-foreground">Only Procurement can approve; switch to Meera.</div>}
          </CardBody>
        </Card>
      )}
      {decided && <div className="mt-4 text-right"><Button variant="secondary" onClick={() => nav("/policy")}>Back to policy</Button></div>}
    </div>
  );
}
