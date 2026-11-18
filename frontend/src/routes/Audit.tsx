import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { dayTime } from "@/lib/format";
import { Badge, Card, Empty, ErrorBox, Input, PageHeader, Select, Spinner } from "@/components/ui";

interface Ev { id: number; actor: string; action: string; entity: string; entity_id: string; before: unknown; after: unknown; at: string }

export default function AuditPage() {
  const [entity, setEntity] = useState("");
  const [actor, setActor] = useState("");
  const [q, setQ] = useState("");
  const ev = useQuery({
    queryKey: ["audit", entity, actor],
    queryFn: () => api.get<Ev[]>(`/api/audit?limit=500${entity ? `&entity=${entity}` : ""}${actor ? `&actor=${actor}` : ""}`),
  });
  const rows = (ev.data ?? []).filter((e) => !q || JSON.stringify(e).toLowerCase().includes(q.toLowerCase()));
  return (
    <div className="mx-auto max-w-5xl">
      <PageHeader title="Audit trail" subtitle="Every state change: who, when, what changed (append-only)." />
      <div className="mb-3 flex flex-wrap gap-2">
        <Select value={entity} onChange={(e) => setEntity(e.target.value)}>
          <option value="">All entities</option>
          {["requirement", "purchase_order", "policy_version", "policy_amendment", "contract", "run", "pr", "kit"].map((x) => <option key={x}>{x}</option>)}
        </Select>
        <Select value={actor} onChange={(e) => setActor(e.target.value)}><option value="">Anyone</option>{["Asha", "Rahul", "Meera", "seed", "api"].map((x) => <option key={x}>{x}</option>)}</Select>
        <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search…" className="w-56" />
      </div>
      {ev.isLoading ? <Spinner /> : ev.isError ? <ErrorBox error={ev.error} /> : rows.length === 0 ? <Empty title="No events" /> : (
        <Card>
          <ol className="divide-y divide-border">
            {rows.map((e) => (
              <li key={e.id} className="flex gap-3 px-4 py-2.5 text-sm">
                <div className="w-36 shrink-0 text-xs text-muted-foreground">{dayTime(e.at)}</div>
                <div className="flex-1">
                  <div><b>{e.actor}</b> · <Badge className="bg-slate-50 text-slate-700 ring-slate-500/20">{e.action}</Badge> {e.entity} <span className="font-mono text-xs">{e.entity_id}</span></div>
                  {(e.before != null || e.after != null) && (
                    <details className="mt-1"><summary className="cursor-pointer text-xs text-muted-foreground">details</summary>
                      <pre className="mt-1 max-h-64 overflow-auto whitespace-pre-wrap break-all rounded bg-muted p-2 text-[11px]">{JSON.stringify({ before: e.before, after: e.after }, null, 1)}</pre>
                    </details>
                  )}
                </div>
              </li>
            ))}
          </ol>
        </Card>
      )}
    </div>
  );
}
