import { useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, CheckCircle2, ChevronRight, CircleSlash, FileSignature, Gavel, ListChecks, Star, XCircle } from "lucide-react";
import { api } from "@/lib/api";
import type { ContractOpt, LadderStep, ReqDetail, ReqSummary } from "@/lib/types";
import { day, dayTime, inr, qty } from "@/lib/format";
import {
  Badge, Bar, Button, Card, CardBody, CardHeader, CardTitle, Dialog, DialogContent, DialogTrigger, ErrorBox, FlagBadge, Input,
  Label, Notice, RouteBadge, Select, Spinner, StatusBadge, Textarea,
} from "@/components/ui";

const SOURCE_TEXT: Record<string, string> = {
  contract_rate: "contract rate",
  contract_rate_out_of_ceiling: "lowest applicable contract rate (ceiling exhausted)",
  last_po_price: "latest PO price (365 days)",
  standard_price: "item standard price",
  requester_estimate: "requester's estimate",
};

function fmtFact(v: unknown): string {
  if (v === true) return "yes";
  if (v === false) return "no";
  if (v === null || v === undefined) return "—";
  if (Array.isArray(v)) return v.join(", ") || "—";
  return String(v);
}

export default function RequirementPage() {
  const { id } = useParams();
  const [params] = useSearchParams();
  const nav = useNavigate();
  const qc = useQueryClient();
  const runId = params.get("run");
  const queue = params.get("queue") ?? "";
  const r = useQuery({ queryKey: ["req", id], queryFn: () => api.get<ReqDetail>(`/api/requirements/${id}`) });
  const siblings = useQuery({
    queryKey: ["reqs", runId],
    queryFn: () => api.get<ReqSummary[]>(`/api/requirements?run_id=${runId}`),
    enabled: !!runId,
  });
  const nextOpen = () => {
    const open = (siblings.data ?? []).filter((s) => s.status === "OPEN" && String(s.id) !== id &&
      (queue === "pos" ? s.decision === "PO" : queue === "sourcing" ? s.decision === "SOURCING_REQUEST" : queue === "review" ? s.review_flags.length > 0 : true));
    return open[0];
  };
  const approve = useMutation({
    mutationFn: () => api.post<Record<string, unknown>>(`/api/requirements/${id}/approve`),
    onSuccess: () => {
      qc.invalidateQueries();
      const n = nextOpen();
      if (n) nav(`/requirements/${n.id}?queue=${queue}&run=${runId}`);
    },
  });

  if (r.isLoading) return <Spinner />;
  if (r.isError) return <ErrorBox error={r.error} />;
  const d = r.data!;
  const t = d.trace;
  const isPO = d.decision === "PO";
  const qtys = d.lines.map((l) => String(l.qty));
  const fired = t.ladder.find((s) => s.fired);

  return (
    <div className="mx-auto max-w-6xl">
      <button onClick={() => nav(runId ? `/inbox?run=${runId}` : "/inbox")} className="mb-3 inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft className="h-4 w-4" /> Inbox</button>
      <div className="mb-5 flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-xl font-semibold">{d.group_code}</h1>
            <RouteBadge route={d.route} className="text-sm" />
            <StatusBadge status={d.status} />
            {d.overridden && <Badge className="bg-amber-50 text-amber-800 ring-amber-600/20">overridden</Badge>}
            <Badge className="bg-indigo-50 text-indigo-700 ring-indigo-600/20">Policy v{d.policy_version} · §{d.clause}</Badge>
          </div>
          <div className="mt-1 text-sm text-muted-foreground">{d.item_code} {d.item?.description ?? d.item_description} · {d.plant} · requirement date {day(d.req_date)}{d.emergency && " · Emergency"}</div>
        </div>
        <div className="text-right">
          <div className="num text-2xl font-semibold">{inr(d.value)}</div>
          <div className="text-xs text-muted-foreground">requirement value</div>
        </div>
      </div>

      <Card className="mb-4 border-primary/30">
        <CardBody className="flex flex-wrap items-center gap-4">
          <div className="flex-1 text-sm">
            {isPO ? <>Place a <b>{d.route.replace(/_/g, " ")}</b> with <b>{d.supplier_id} {d.supplier_names[d.supplier_id ?? ""] ?? d.supplier_name}</b> at <b>{inr(d.unit_price, { paise: true })}</b>{d.po_code && <> on <b>{d.po_code}</b></>}.</>
              : d.decision ? <>Launch a <b>{d.route.replace(/_/g, " ")}</b>{d.suggested.length > 0 && <> with {d.suggested.join(", ")}</>}.</> : <>No rule matched: override with a route.</>}
            <div className="mt-1 text-xs text-muted-foreground">{d.reason}</div>
          </div>
          {d.status === "OPEN" ? (
            <div className="flex gap-2">
              <OverrideDialog d={d} />
              <Button size="lg" variant="success" disabled={!d.decision} loading={approve.isPending} onClick={() => approve.mutate()}>
                <CheckCircle2 className="h-4 w-4" /> {isPO ? "Approve PO line" : `Approve & launch ${d.route.replace(/_SOURCING$/, "").replace(/_/g, " ")}`}
              </Button>
            </div>
          ) : <Badge className="bg-emerald-50 text-emerald-700 ring-emerald-600/20"><CheckCircle2 className="h-3 w-3" /> Approved</Badge>}
        </CardBody>
        {approve.isError && <CardBody className="pt-0"><ErrorBox error={approve.error} /></CardBody>}
      </Card>

      <div className="grid gap-4 lg:grid-cols-[1.25fr_1fr]">
        <div className="space-y-4">
          <Card>
            <CardHeader><CardTitle>Value (policy 3.1)</CardTitle></CardHeader>
            <CardBody className="num text-sm">
              {qtys.length > 1 ? `${qtys.map(qty).join(" + ")} = ` : ""}{qty(t.value.qty)} {d.item?.uom ?? ""} × {inr(t.value.price, { paise: true })}
              {" "}<span className="text-muted-foreground">({SOURCE_TEXT[t.value.source] ?? t.value.source}{t.value.ref ? ` ${t.value.ref}` : ""})</span> = <b>{inr(t.value.total)}</b>
              {t.value.source === "last_po_price" && isPO && d.unit_price !== t.value.price && (
                <div className="mt-1 text-xs text-muted-foreground">The PO price is the supplier's own reference price (§6.3); the value uses the latest PO for the item (§3.1b).</div>
              )}
            </CardBody>
          </Card>

          <Card>
            <CardHeader><CardTitle className="flex items-center gap-1.5"><ListChecks className="h-4 w-4" /> Rule ladder (first match wins, §5)</CardTitle></CardHeader>
            <div className="divide-y divide-border">
              {t.ladder.map((s) => <LadderRow key={s.rule} step={s} />)}
              {!fired && <div className="px-4 py-3 text-sm text-red-700">No rule matched.</div>}
            </div>
          </Card>

          <Card>
            <CardHeader><CardTitle>PR lines ({d.lines.length})</CardTitle></CardHeader>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-muted/60 text-xs text-muted-foreground"><tr>{["PR", "Created", "Requester", "Description", "Qty", "Need by", "Urgency", "Match"].map((h) => <th key={h} className="px-3 py-1.5 text-left">{h}</th>)}</tr></thead>
                <tbody>
                  {d.lines.map((l) => (
                    <tr key={`${l.pr_no}/${l.line}`} className="border-t border-border">
                      <td className="whitespace-nowrap px-3 py-1.5 font-medium">{String(l.pr_no)}/{String(l.line)}</td>
                      <td className="whitespace-nowrap px-3 py-1.5 text-xs">{dayTime(String(l.created_at))}</td>
                      <td className="px-3 py-1.5 text-xs">{String(l.requester)}<div className="text-muted-foreground">{String(l.department)}</div></td>
                      <td className="px-3 py-1.5 text-xs">{String(l.description)}{l.item_code ? <div className="text-muted-foreground">code given: {String(l.item_code)}</div> : null}</td>
                      <td className="num whitespace-nowrap px-3 py-1.5">{qty(String(l.qty))} {String(l.uom)}</td>
                      <td className="whitespace-nowrap px-3 py-1.5 text-xs">{day(String(l.need_by))}</td>
                      <td className="px-3 py-1.5 text-xs">{String(l.urgency)}</td>
                      <td className="px-3 py-1.5 text-xs">{String(l.match_method)}{l.match_method === "TEXT" && ` ${Number(l.match_score).toFixed(2)}`}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </div>

        <div className="space-y-4">
          {d.flags.length > 0 && (
            <Card><CardHeader><CardTitle>Flags</CardTitle></CardHeader><CardBody className="flex flex-wrap gap-1.5">{d.flags.map((f) => <FlagBadge key={f} flag={f} />)}</CardBody></Card>
          )}
          {(t.contracts.applicable.length > 0 || t.contracts.excluded.length > 0) && (
            <Card>
              <CardHeader><CardTitle className="flex items-center gap-1.5"><FileSignature className="h-4 w-4" /> Contracts (§4)</CardTitle></CardHeader>
              <CardBody className="space-y-3">
                {t.contracts.applicable.map((c) => <ContractBar key={c.id} c={c} chosen={t.contracts.chosen === c.id} />)}
                {t.contracts.excluded.map((x) => <div key={x.id} className="flex items-center gap-1 text-xs text-muted-foreground"><CircleSlash className="h-3.5 w-3.5" /> {x.id}: not applicable — {x.why}</div>)}
              </CardBody>
            </Card>
          )}
          {t.preferred.length > 0 && (
            <Card>
              <CardHeader><CardTitle className="flex items-center gap-1.5"><Star className="h-4 w-4" /> Preferred suppliers on {day(t.requirement_date)} (§6)</CardTitle></CardHeader>
              <CardBody className="space-y-3">
                {t.preferred.slice(0, 5).map((p) => (
                  <div key={p.supplier} className={`rounded-md border p-2 ${p.supplier === d.supplier_id ? "border-emerald-400 bg-emerald-50/40" : "border-border"}`}>
                    <div className="flex items-center justify-between text-sm">
                      <span><b>#{p.rank}</b> {p.supplier} {d.supplier_names[p.supplier] ?? ""}</span>
                      <span className="num text-xs text-muted-foreground">score {Number(p.score).toFixed(3)} · ref {p.reference_price ? inr(p.reference_price, { paise: true }) : "—"}</span>
                    </div>
                    <div className="mt-1.5 grid grid-cols-5 gap-1">
                      {Object.entries(p.components).map(([k, v]) => (
                        <div key={k} title={`${k}: ${Number(v).toFixed(3)}`}><Bar value={Number(v)} max={0.3} className="h-1.5" /><div className="mt-0.5 text-[10px] text-muted-foreground">{k.replace("_", "-")}</div></div>
                      ))}
                    </div>
                    <div className="mt-1 text-xs text-muted-foreground">{p.explanation}</div>
                  </div>
                ))}
              </CardBody>
            </Card>
          )}
          {t.outcome.suggested.length > 0 && (
            <Card>
              <CardHeader><CardTitle>Suggested for sourcing (§6.4)</CardTitle></CardHeader>
              <CardBody className="space-y-1.5 text-sm">
                {t.outcome.suggested.map((s, i) => (
                  <div key={s.supplier} className="flex gap-2"><span className="w-5 text-muted-foreground">{i + 1}.</span><div><b>{s.supplier}</b> {d.supplier_names[s.supplier] ?? ""}<div className="text-xs text-muted-foreground">{s.source === "preferred" ? "from the preferred list" : "category top-up"} — {s.why}</div></div></div>
                ))}
              </CardBody>
            </Card>
          )}
          {d.po && (
            <Card>
              <CardHeader><CardTitle>Purchase order</CardTitle><Link to={`/po/${d.po.id}`} className="text-xs text-primary hover:underline">Open {d.po.code} <ChevronRight className="inline h-3 w-3" /></Link></CardHeader>
              <CardBody className="text-sm">{d.po.code} · {d.po.lines.length} line(s) · {inr(d.po.total)} · <StatusBadge status={d.po.status} /></CardBody>
            </Card>
          )}
          <Card>
            <CardHeader><CardTitle className="flex items-center gap-1.5"><Gavel className="h-4 w-4" /> History</CardTitle></CardHeader>
            <CardBody className="space-y-2 text-xs">
              {d.history.map((h) => (
                <div key={h.id} className="border-l-2 border-border pl-2">
                  <div className="font-medium">{h.status === "OVERRIDDEN" ? "Override" : "Engine decision"} · {h.route} {h.supplier_id ?? ""} · {inr(h.value)}</div>
                  <div className="text-muted-foreground">{h.created_by}, {dayTime(h.created_at)}</div>
                </div>
              ))}
              {d.overrides.map((o) => <Notice key={o.id} tone="warn" className="text-xs">“{o.comment}” — {o.by}, {dayTime(o.at)}</Notice>)}
              {d.sourcing_events.map((e) => <div key={e.id}>Sourcing event <b>{e.code}</b> ({e.kind}) launched by {e.created_by}</div>)}
              {d.audit.map((a, i) => <div key={i} className="text-muted-foreground">{a.action} by {a.actor}, {dayTime(a.at)}</div>)}
            </CardBody>
          </Card>
        </div>
      </div>
    </div>
  );
}

function LadderRow({ step }: { step: LadderStep }) {
  const facts = Object.entries(step.facts);
  const params = Object.entries(step.params);
  return (
    <div className={`flex gap-3 px-4 py-2.5 ${step.fired ? "bg-emerald-50/60" : ""}`}>
      <div className="pt-0.5">{step.fired ? <CheckCircle2 className="h-4 w-4 text-emerald-600" /> : step.matched ? <CircleSlash className="h-4 w-4 text-amber-600" /> : <XCircle className="h-4 w-4 text-muted-foreground" />}</div>
      <div className="flex-1">
        <div className="text-sm"><span className="font-mono text-xs text-muted-foreground">{step.rule}</span> <b>{step.name}</b> <span className="text-xs text-muted-foreground">§{step.clause} → {step.route}</span></div>
        <div className="mt-0.5 flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-muted-foreground">
          {facts.map(([k, v]) => <span key={k}><span className="font-mono">{k}</span> = <b className="text-foreground">{fmtFact(v)}</b></span>)}
          {params.map(([k, v]) => <span key={k}><span className="font-mono">{k}</span> = {Number(v).toLocaleString("en-IN")}</span>)}
        </div>
        {step.note && <div className="text-xs text-amber-700">{step.note}</div>}
      </div>
    </div>
  );
}

function ContractBar({ c, chosen }: { c: ContractOpt; chosen: boolean }) {
  const cap = Number(c.cap);
  const consumed = Number(c.consumed);
  const required = Number(c.required);
  return (
    <div className={`rounded-md border p-2 ${chosen ? "border-emerald-400" : "border-border"}`}>
      <div className="flex items-center justify-between text-sm">
        <span><b>{c.id}</b> · {c.supplier} · {inr(c.rate, { paise: true })}{c.source === "PDF" && <Badge className="ml-1 bg-violet-50 text-violet-700 ring-violet-600/20">PDF</Badge>}</span>
        {c.usable ? <Badge className="bg-emerald-50 text-emerald-700 ring-emerald-600/20">{chosen ? "used" : "usable"}</Badge> : <Badge className="bg-red-50 text-red-700 ring-red-600/20">ceiling insufficient</Badge>}
      </div>
      <div className="mt-2 flex h-2.5 w-full overflow-hidden rounded-full bg-muted">
        <div className="h-full bg-slate-400" style={{ width: `${Math.min(100, (consumed / cap) * 100)}%` }} title="consumed before" />
        <div className={`h-full ${c.usable ? "bg-emerald-500" : "bg-red-400"}`} style={{ width: `${Math.min(100 - Math.min(100, (consumed / cap) * 100), (required / cap) * 100)}%` }} title="this requirement" />
      </div>
      <div className="num mt-1 text-xs text-muted-foreground">consumed {inr(consumed)} + this {inr(required)} vs ceiling {inr(cap)} · left before {inr(c.remaining)}</div>
    </div>
  );
}

function OverrideDialog({ d }: { d: ReqDetail }) {
  const qc = useQueryClient();
  const [route, setRoute] = useState(d.route);
  const [supplier, setSupplier] = useState(d.supplier_id ?? "");
  const [price, setPrice] = useState(d.unit_price ?? "");
  const [comment, setComment] = useState("");
  const [open, setOpen] = useState(false);
  const isPO = d.routes.po.includes(route);
  const m = useMutation({
    mutationFn: () => api.post(`/api/requirements/${d.id}/override`, { route, supplier_id: isPO ? supplier : null, unit_price: isPO ? price : null, comment }),
    onSuccess: () => { qc.invalidateQueries(); setOpen(false); },
  });
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild><Button size="lg" variant="secondary">Override…</Button></DialogTrigger>
      <DialogContent title={`Override ${d.group_code}`} description="The original decision is kept; your override is recorded with your name and reason (policy 8.1).">
        <div className="space-y-3">
          <div><Label htmlFor="ov-route">Route</Label><Select id="ov-route" className="w-full" value={route} onChange={(e) => setRoute(e.target.value)}>
            <optgroup label="Purchase order">{d.routes.po.map((r) => <option key={r}>{r}</option>)}</optgroup>
            <optgroup label="Sourcing">{d.routes.sourcing.map((r) => <option key={r}>{r}</option>)}</optgroup>
          </Select></div>
          {isPO && <>
            <div><Label htmlFor="ov-sup">Supplier (Active suppliers only)</Label><Select id="ov-sup" className="w-full" value={supplier} onChange={(e) => setSupplier(e.target.value)}>
              <option value="">Choose…</option>
              {d.eligible_suppliers.map((s) => <option key={s.id} value={s.id}>{s.id} {s.name} — {s.categories.join(", ")}</option>)}
            </Select></div>
            <div><Label htmlFor="ov-price">Unit price (₹)</Label><Input id="ov-price" value={price} onChange={(e) => setPrice(e.target.value)} /></div>
          </>}
          <div><Label htmlFor="ov-reason">Reason (required)</Label><Textarea id="ov-reason" value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Why is the policy outcome not right here?" /></div>
          {m.isError && <ErrorBox error={m.error} />}
          <div className="flex justify-end"><Button disabled={!comment.trim() || (isPO && (!supplier || !price))} loading={m.isPending} onClick={() => m.mutate()}>Save override</Button></div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
