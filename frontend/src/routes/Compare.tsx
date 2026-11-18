import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { api, download } from "@/lib/api";
import type { Run } from "@/lib/types";
import { inr } from "@/lib/format";
import { Badge, Button, Card, CardBody, CardHeader, CardTitle, Empty, ErrorBox, PageHeader, RouteBadge, Select, Spinner, Stat } from "@/components/ui";

interface Diff {
  a: Run; b: Run;
  summary: { lines_compared: number; lines_changed: number; route_moves: Record<string, number>; only_in_a: number; only_in_b: number; grouping_changes: number };
  changed: { pr_no: string; pr_line: string; changes: Record<string, [string, string]>; old_route: string; new_route: string; new_reason: string }[];
  grouping_changes: { pr_no: string; pr_line: string; kind: string; old: string[]; new: string[] }[];
}

export default function ComparePage() {
  const [params] = useSearchParams();
  const runs = useQuery({ queryKey: ["runs"], queryFn: () => api.get<Run[]>("/api/runs") });
  const batches = (runs.data ?? []).filter((r) => r.kind !== "IMPACT");
  const [a, setA] = useState(params.get("a") ?? "");
  const [b, setB] = useState(params.get("b") ?? "");
  const A = a || String(batches[1]?.id ?? "");
  const B = b || String(batches[0]?.id ?? "");
  const diff = useQuery({ queryKey: ["compare", A, B], queryFn: () => api.get<Diff>(`/api/runs/compare?a=${A}&b=${B}`), enabled: !!A && !!B && A !== B });
  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader
        title="Compare runs"
        subtitle="Run 1 vs Run 2: only what the amendment implies should change."
        actions={<Button size="lg" disabled={!diff.data} onClick={() => download(`/api/runs/compare/export.csv?a=${A}&b=${B}`, `compare_${A}_${B}.csv`)}><Download className="h-4 w-4" /> Export diff CSV</Button>}
      />
      <Card className="mb-4">
        <CardBody className="flex flex-wrap items-center gap-3 text-sm">
          <span>Run A</span><Select value={A} onChange={(e) => setA(e.target.value)}>{batches.map((r) => <option key={r.id} value={r.id}>#{r.id} {r.name}</option>)}</Select>
          <span>→ Run B</span><Select value={B} onChange={(e) => setB(e.target.value)}>{batches.map((r) => <option key={r.id} value={r.id}>#{r.id} {r.name}</option>)}</Select>
        </CardBody>
      </Card>
      {A === B ? <Empty title="Choose two different runs" /> : diff.isLoading ? <Spinner /> : diff.isError ? <ErrorBox error={diff.error} /> : diff.data && (
        <>
          <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
            <Stat label="Lines compared" value={diff.data.summary.lines_compared} />
            <Stat label="Lines changed" value={diff.data.summary.lines_changed} />
            <Stat label="Route moves" value={Object.values(diff.data.summary.route_moves).reduce((x, y) => x + y, 0)} />
            <Stat label="Grouping changes" value={diff.data.summary.grouping_changes} sub="requirement / PO membership" />
          </div>
          {Object.keys(diff.data.summary.route_moves).length > 0 && (
            <div className="mb-4 flex flex-wrap gap-2">{Object.entries(diff.data.summary.route_moves).map(([k, v]) => <Badge key={k} className="bg-indigo-50 text-indigo-700 ring-indigo-600/20">{k}: {v}</Badge>)}</div>
          )}
          <Card>
            <CardHeader><CardTitle>Changed lines</CardTitle></CardHeader>
            {diff.data.changed.length === 0 ? <CardBody><Empty title="No decision changed">The two runs agree on every line.</Empty></CardBody> : (
              <div className="max-h-[60vh] overflow-auto">
                <table className="w-full text-sm">
                  <thead className="sticky top-0 bg-muted text-xs text-muted-foreground"><tr><th className="px-3 py-2 text-left">PR line</th><th className="text-left">Route</th><th className="text-left">Changes</th><th className="text-left">Why now (Run B)</th></tr></thead>
                  <tbody>
                    {diff.data.changed.map((c) => (
                      <tr key={`${c.pr_no}/${c.pr_line}`} className="border-t border-border align-top">
                        <td className="whitespace-nowrap px-3 py-2 font-medium">{c.pr_no}/{c.pr_line}</td>
                        <td className="whitespace-nowrap py-2">{c.old_route === c.new_route ? <RouteBadge route={c.new_route} /> : <><RouteBadge route={c.old_route} /> → <RouteBadge route={c.new_route} /></>}</td>
                        <td className="py-2 text-xs">{Object.entries(c.changes).filter(([k]) => k !== "route").map(([k, [o, n]]) => <div key={k}><span className="text-muted-foreground">{k}</span> {k === "group_value_inr" || k === "unit_price" ? `${inr(o)} → ${inr(n)}` : `${o || "—"} → ${n || "—"}`}</div>)}</td>
                        <td className="max-w-md py-2 pr-3 text-xs text-muted-foreground">{c.new_reason}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </>
      )}
    </div>
  );
}
