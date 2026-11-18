import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { ArrowLeftRight, CheckCircle2, Download, Inbox, XCircle } from "lucide-react";
import { api, download } from "@/lib/api";
import type { DecisionRow, ReqSummary, Run } from "@/lib/types";
import { dayTime, inr, inrShort } from "@/lib/format";
import { DataTable } from "@/components/DataTable";
import { Button, Card, CardBody, CardHeader, CardTitle, ErrorBox, PageHeader, RouteBadge, Select, Spinner, Stat } from "@/components/ui";

const EXPECTED_COLUMNS = "pr_no,pr_line,resolved_item_code,group_id,po_id,decision,route,supplier_id,unit_price,group_value_inr,suggested_supplier_ids,policy_version,reason";

export default function RunPage() {
  const { id } = useParams();
  const nav = useNavigate();
  const [route, setRoute] = useState("");
  const run = useQuery({ queryKey: ["run", id], queryFn: () => api.get<Run & { columns: string[]; decisions: DecisionRow[] }>(`/api/runs/${id}`) });
  const reqs = useQuery({ queryKey: ["reqs", id], queryFn: () => api.get<ReqSummary[]>(`/api/requirements?run_id=${id}`) });
  const suppliers = useQuery({ queryKey: ["suppliers"], queryFn: () => api.get<{ id: string; status: string }[]>("/api/suppliers") });
  const reqId = useMemo(() => Object.fromEntries((reqs.data ?? []).map((r) => [r.group_code, r.id])), [reqs.data]);

  const columns = useMemo<ColumnDef<DecisionRow, unknown>[]>(() => [
    { accessorKey: "pr_no", header: "PR", cell: (c) => <span className="whitespace-nowrap font-medium">{c.row.original.pr_no}/{c.row.original.pr_line}</span> },
    { accessorKey: "resolved_item_code", header: "Item", cell: (c) => <span className="whitespace-nowrap">{c.getValue() as string}</span> },
    { accessorKey: "group_id", header: "Requirement", cell: (c) => {
      const g = c.getValue() as string;
      return g && reqId[g] ? <Link onClick={(e) => e.stopPropagation()} to={`/requirements/${reqId[g]}`} className="text-primary hover:underline">{g}</Link> : g;
    } },
    { accessorKey: "po_id", header: "PO", cell: (c) => <span className="whitespace-nowrap">{c.getValue() as string}</span> },
    { accessorKey: "route", header: "Route", cell: (c) => <RouteBadge route={c.getValue() as string} /> },
    { accessorKey: "supplier_id", header: "Supplier / suggested", cell: (c) => c.row.original.supplier_id || <span className="text-xs text-muted-foreground">{c.row.original.suggested_supplier_ids.replace(/;/g, ", ")}</span> },
    { accessorKey: "unit_price", header: "Unit price", cell: (c) => <span className="num">{c.getValue() ? inr(c.getValue() as string, { paise: true }) : ""}</span> },
    { accessorKey: "group_value_inr", header: "Value", sortingFn: (a, b) => Number(a.original.group_value_inr || 0) - Number(b.original.group_value_inr || 0),
      cell: (c) => <span className="num whitespace-nowrap">{c.getValue() ? inr(c.getValue() as string) : ""}</span> },
    { accessorKey: "policy_version", header: "v" },
    { accessorKey: "reason", header: "Why", cell: (c) => <div className="max-w-md truncate text-xs text-muted-foreground" title={c.getValue() as string}>{c.getValue() as string}</div> },
  ], [reqId]);

  if (run.isLoading) return <Spinner />;
  if (run.isError) return <ErrorBox error={run.error} />;
  const r = run.data!;
  const rows = route ? r.decisions.filter((d) => d.route === route) : r.decisions;
  const statuses = Object.fromEntries((suppliers.data ?? []).map((s) => [s.id, s.status]));
  const used = r.decisions.flatMap((d) => [d.supplier_id, ...d.suggested_supplier_ids.split(";")]).filter(Boolean);
  const bad = used.filter((s) => statuses[s] && statuses[s] !== "Active");
  const checks = [
    { ok: r.columns.join(",") === EXPECTED_COLUMNS, text: "Columns exactly as specified, in order" },
    { ok: r.decisions.length === r.summary.input_rows, text: `${r.decisions.length} rows = ${r.summary.input_rows} input lines, in input order` },
    { ok: suppliers.isSuccess && bad.length === 0, text: bad.length ? `Non-Active suppliers used: ${[...new Set(bad)].join(", ")}` : "No Blocked/Inactive supplier in any PO or suggestion" },
    { ok: r.decisions.every((d) => d.route !== "NEEDS_REVIEW"), text: "Every requirement matched a rule" },
  ];
  const np = r.decisions.filter((d) => d.route === "NOT_PROCESSED");

  return (
    <div className="mx-auto max-w-[1400px]">
      <PageHeader
        title={r.name}
        subtitle={<>Run #{r.id} · {r.input_file ?? "live"} · {dayTime(r.created_at)} by {r.created_by} · {r.policy_pin ? `pinned to v${r.policy_pin}` : `policy v${r.summary.policy_versions_used.join(", v")} by effective date`} · {r.duration_ms} ms</>}
        actions={<>
          <Button variant="secondary" onClick={() => nav(`/inbox?run=${r.id}`)}><Inbox className="h-4 w-4" /> Open in inbox</Button>
          <Button variant="secondary" onClick={() => nav(`/compare?b=${r.id}`)}><ArrowLeftRight className="h-4 w-4" /> Compare</Button>
          <Button onClick={() => download(`/api/runs/${r.id}/export.csv`, `decisions_run${r.id}.csv`)}><Download className="h-4 w-4" /> Download decisions CSV</Button>
        </>}
      />
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-5">
        <Stat label="PR lines" value={r.summary.input_rows} sub={`${r.summary.not_processed} not processed`} />
        <Stat label="Requirements" value={r.summary.requirements} sub={inrShort(r.summary.total_value)} />
        <Stat label="Purchase orders" value={r.summary.purchase_orders} sub="after consolidation (§7)" />
        <Stat label="Sourcing requests" value={Object.entries(r.summary.routes_by_requirement).filter(([k]) => !k.endsWith("_PO")).reduce((a, [, v]) => a + v, 0)} />
        <Stat label="Flags for review" value={Object.values(r.summary.flags ?? {}).reduce((a, b) => a + b, 0)} sub="see inbox" />
      </div>
      <div className="mb-4 grid gap-4 lg:grid-cols-[1fr_1.2fr]">
        <Card>
          <CardHeader><CardTitle>Built-in checks</CardTitle></CardHeader>
          <CardBody className="space-y-1.5">
            {checks.map((c) => (
              <div key={c.text} className="flex items-center gap-2 text-sm">
                {c.ok ? <CheckCircle2 className="h-4 w-4 text-emerald-600" /> : <XCircle className="h-4 w-4 text-red-600" />} {c.text}
              </div>
            ))}
            {np.length > 0 && (
              <div className="pt-2 text-xs text-muted-foreground">
                Not processed: {np.map((d) => `${d.pr_no}/${d.pr_line} (${d.reason.split(" - ").pop()})`).join(" · ")}
              </div>
            )}
          </CardBody>
        </Card>
        <Card>
          <CardHeader><CardTitle>Requirements by route</CardTitle></CardHeader>
          <CardBody className="flex flex-wrap gap-2">
            {Object.entries(r.summary.routes_by_requirement).map(([k, v]) => (
              <button key={k} onClick={() => setRoute(route === k ? "" : k)} className={`flex items-center gap-1 rounded-md border px-2 py-1 ${route === k ? "border-primary" : "border-border"}`}>
                <RouteBadge route={k} /> <span className="num text-sm font-semibold">{v}</span>
              </button>
            ))}
          </CardBody>
        </Card>
      </div>
      <DataTable
        data={rows}
        columns={columns}
        placeholder="Search PR, item, supplier, reason…"
        toolbar={
          <Select value={route} onChange={(e) => setRoute(e.target.value)} className="h-8">
            <option value="">All routes</option>
            {Object.keys(r.summary.routes_by_line).map((k) => <option key={k} value={k}>{k}</option>)}
          </Select>
        }
        onRowClick={(d) => d.group_id && reqId[d.group_id] && nav(`/requirements/${reqId[d.group_id]}`)}
      />
    </div>
  );
}
