import { useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, CheckCircle2, Package, Radio, Search } from "lucide-react";
import { api } from "@/lib/api";
import type { Inbox, ReqSummary, Run } from "@/lib/types";
import { FLAG_TEXT, day, inr, inrShort } from "@/lib/format";
import { WelcomePanel } from "@/components/Layout";
import {
  Badge, Button, Card, Empty, ErrorBox, FlagBadge, Input, PageHeader, RouteBadge, Select, Spinner, Stat, StatusBadge,
} from "@/components/ui";

type Queue = "pos" | "sourcing" | "review" | "done";

export default function InboxPage() {
  const [params, setParams] = useSearchParams();
  const nav = useNavigate();
  const qc = useQueryClient();
  const runId = params.get("run") ?? "";
  const [queue, setQueue] = useState<Queue>((params.get("q") as Queue) || "pos");
  const [route, setRoute] = useState("");
  const [plant, setPlant] = useState("");
  const [flag, setFlag] = useState("");
  const [q, setQ] = useState("");
  const runs = useQuery({ queryKey: ["runs"], queryFn: () => api.get<Run[]>("/api/runs") });
  const inbox = useQuery({ queryKey: ["inbox", runId], queryFn: () => api.get<Inbox>(`/api/inbox${runId ? `?run_id=${runId}` : ""}`) });
  const approvePo = useMutation({
    mutationFn: (poId: number) => api.post(`/api/purchase-orders/${poId}/approve`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["inbox"] }),
  });

  const match = (r: ReqSummary) =>
    (!route || r.route === route) && (!plant || r.plant === plant) && (!flag || r.flags.includes(flag)) &&
    (!q || `${r.group_code} ${r.item_code} ${r.item_description} ${r.supplier_id ?? ""} ${r.lines.map((l) => l.pr_no).join(" ")}`.toLowerCase().includes(q.toLowerCase()));

  const data = inbox.data;
  const allReqs = useMemo(() => {
    if (!data) return [] as ReqSummary[];
    const qs = data.queues;
    return [...qs.pos.items.flatMap((p) => p.requirements), ...qs.sourcing.items, ...qs.review.items, ...qs.done.items];
  }, [data]);
  const routes = [...new Set(allReqs.map((r) => r.route))].sort();
  const plants = [...new Set(allReqs.map((r) => r.plant))].sort();
  const flags = [...new Set(allReqs.flatMap((r) => r.flags))].sort();

  if (inbox.isLoading) return <Spinner />;
  if (inbox.isError) return <ErrorBox error={inbox.error} />;
  if (!data?.run) return <Empty title="Nothing to review yet">Process a batch on the Batches page, or raise a PR in Chat.</Empty>;
  const qs = data.queues;
  const pos = qs.pos.items.map((p) => ({ ...p, requirements: p.requirements.filter(match) })).filter((p) => p.requirements.length);
  const list = (queue === "sourcing" ? qs.sourcing.items : queue === "review" ? qs.review.items : queue === "done" ? qs.done.items : []).filter(match);
  const next = queue === "pos" ? pos[0]?.requirements[0] : list.find((r) => r.status === "OPEN") ?? list[0];

  return (
    <div className="mx-auto max-w-6xl">
      <WelcomePanel />
      <PageHeader
        title="Inbox"
        subtitle={
          <span className="flex items-center gap-2">
            <Select value={runId || String(data.run.id)} onChange={(e) => setParams({ run: e.target.value })} className="h-8">
              {(runs.data ?? []).map((r) => <option key={r.id} value={r.id}>{r.kind === "LIVE" ? "● " : ""}{r.name} (#{r.id})</option>)}
            </Select>
            {data.run.kind === "LIVE" && <Badge className="bg-emerald-50 text-emerald-700 ring-emerald-600/20"><Radio className="h-3 w-3" /> live PRs from chat</Badge>}
          </span>
        }
        actions={
          <Button size="lg" disabled={!next} onClick={() => next && nav(`/requirements/${next.id}?queue=${queue}&run=${data.run!.id}`)}>
            Review next <ArrowRight className="h-4 w-4" />
          </Button>
        }
      />
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="POs ready to place" value={qs.pos.count} sub={`${qs.pos.requirements} requirements · ${inrShort(qs.pos.total)}`} active={queue === "pos"} onClick={() => setQueue("pos")} />
        <Stat label="Sourcing to launch" value={qs.sourcing.count} sub={inrShort(qs.sourcing.total)} active={queue === "sourcing"} onClick={() => setQueue("sourcing")} />
        <Stat label="Needs review" value={qs.review.count} sub="flagged for a buyer's eye" active={queue === "review"} onClick={() => setQueue("review")} />
        <Stat label="Done" value={qs.done.count} sub={inrShort(qs.done.total)} active={queue === "done"} onClick={() => setQueue("done")} />
      </div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="relative"><Search className="absolute left-2 top-2.5 h-4 w-4 text-muted-foreground" /><Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="PR, item, supplier…" className="h-9 w-56 pl-8" /></div>
        <Select value={route} onChange={(e) => setRoute(e.target.value)}><option value="">All routes</option>{routes.map((r) => <option key={r}>{r}</option>)}</Select>
        <Select value={plant} onChange={(e) => setPlant(e.target.value)}><option value="">All plants</option>{plants.map((p) => <option key={p}>{p}</option>)}</Select>
        <Select value={flag} onChange={(e) => setFlag(e.target.value)}><option value="">Any flag</option>{flags.map((f) => <option key={f} value={f}>{FLAG_TEXT[f] ?? f}</option>)}</Select>
      </div>

      {queue === "pos" ? (
        pos.length === 0 ? <Empty title="No POs waiting">Every PO decision is approved, or the filters hide them.</Empty> : (
          <div className="space-y-3">
            {pos.map((p) => (
              <Card key={p.po_code} data-testid="po-card" data-consolidated={p.requirements.length > 1 ? "true" : "false"}>
                <div className="flex flex-wrap items-center gap-3 border-b border-border px-4 py-3">
                  <Package className="h-5 w-5 text-muted-foreground" />
                  <div className="flex-1">
                    <div className="flex items-center gap-2 text-sm font-semibold">
                      {p.po_id ? <Link to={`/po/${p.po_id}`} className="hover:underline">{p.po_code}</Link> : p.po_code}
                      <RouteBadge route={p.route} />
                      {p.requirements.length > 1 && <Badge className="bg-slate-50 text-slate-600 ring-slate-500/20">{p.requirements.length} requirements consolidated (§7)</Badge>}
                    </div>
                    <div className="text-xs text-muted-foreground">{p.supplier_id} {p.supplier_name} · {p.plant}</div>
                  </div>
                  <div className="num text-right text-sm font-semibold">{inr(p.total)}</div>
                  {p.po_id && <Button size="sm" variant="success" loading={approvePo.isPending && approvePo.variables === p.po_id} onClick={() => approvePo.mutate(p.po_id!)}><CheckCircle2 className="h-4 w-4" /> Approve PO</Button>}
                </div>
                <ReqTable rows={p.requirements} runId={data.run!.id} queue="pos" compact />
              </Card>
            ))}
          </div>
        )
      ) : list.length === 0 ? (
        <Empty title={queue === "done" ? "Nothing approved yet" : "Queue is empty"} />
      ) : (
        <Card><ReqTable rows={list} runId={data.run.id} queue={queue} /></Card>
      )}
      {approvePo.isError && <div className="mt-3"><ErrorBox error={approvePo.error} /></div>}
    </div>
  );
}

function ReqTable({ rows, runId, queue, compact }: { rows: ReqSummary[]; runId: number; queue: Queue; compact?: boolean }) {
  const nav = useNavigate();
  return (
    <table className="w-full text-sm">
      {!compact && (
        <thead className="bg-muted/60 text-xs text-muted-foreground">
          <tr>{["Requirement", "Item", "Plant", "Date", "Route", "Supplier / suggested", "Value", "Flags", ""].map((h) => <th key={h} className="px-3 py-2 text-left font-semibold">{h}</th>)}</tr>
        </thead>
      )}
      <tbody>
        {rows.map((r) => (
          <tr key={r.id} onClick={() => nav(`/requirements/${r.id}?queue=${queue}&run=${runId}`)} className="cursor-pointer border-t border-border hover:bg-accent">
            <td className="px-3 py-2"><div className="font-medium">{r.group_code}</div><div className="text-xs text-muted-foreground">{r.lines.map((l) => `${l.pr_no}/${l.line}`).join(", ")}</div></td>
            <td className="px-3 py-2"><div>{r.item_code}</div><div className="max-w-[220px] truncate text-xs text-muted-foreground">{r.item_description}</div></td>
            <td className="px-3 py-2">{r.plant}</td>
            <td className="whitespace-nowrap px-3 py-2 text-xs">{day(r.req_date)}{r.emergency && <Badge className="ml-1 bg-rose-50 text-rose-700 ring-rose-600/20">Emergency</Badge>}</td>
            {!compact && <td className="px-3 py-2"><RouteBadge route={r.route} /></td>}
            <td className="px-3 py-2 text-xs">{r.supplier_id ? `${r.supplier_id} ${r.supplier_name}` : r.suggested.join(", ") || "—"}</td>
            <td className="num whitespace-nowrap px-3 py-2 text-right font-medium">{inr(r.value)}{r.unit_price && <div className="text-xs font-normal text-muted-foreground">@ {inr(r.unit_price, { paise: true })}</div>}</td>
            <td className="px-3 py-2"><div className="flex max-w-[220px] flex-wrap gap-1">{r.review_flags.slice(0, 2).map((f) => <FlagBadge key={f} flag={f} />)}{r.review_flags.length > 2 && <span className="text-xs text-muted-foreground">+{r.review_flags.length - 2}</span>}</div></td>
            {!compact && <td className="px-3 py-2"><StatusBadge status={r.status} /></td>}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
