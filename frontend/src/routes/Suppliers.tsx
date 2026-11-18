import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Download, Info } from "lucide-react";
import { api, download } from "@/lib/api";
import { inr } from "@/lib/format";
import { useMeta } from "@/components/Layout";
import { Bar, Button, Card, CardBody, CardHeader, CardTitle, ErrorBox, Input, Label, Notice, PageHeader, Select, Spinner, StatusBadge } from "@/components/ui";

interface Overview { item_code: string; description: string; category: string; suppliers: { rank: number; supplier_id: string; name: string; reference_price: string | null; score: string }[] }
interface Detail {
  item: { code: string; description: string; category: string; uom: string };
  as_of: string; policy_version: string; weights: Record<string, string>;
  ranked: { rank: number; supplier_id: string; name: string; score: string; components: Record<string, string>; po_count: number; last_po_date: string | null;
            days_since_last_po: number | null; recency: string; has_contract: boolean; contracts: string[]; on_time_pct: string; quality_rating: string;
            reference_price: string | null; reference_ref: string; explanation: string }[];
  excluded: { supplier_id: string; name: string; status: string }[];
}

export default function SuppliersPage() {
  const meta = useMeta();
  const [asOf, setAsOf] = useState("");
  const date = asOf || meta.data?.today || "";
  const [item, setItem] = useState("ITM-1048");
  const overview = useQuery({ queryKey: ["pref", date], queryFn: () => api.get<Overview[]>(`/api/preferred-suppliers?as_of=${date}`), enabled: !!date });
  const detail = useQuery({ queryKey: ["pref-item", item, date], queryFn: () => api.get<Detail>(`/api/preferred-suppliers/${item}?as_of=${date}`), enabled: !!date && !!item });
  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader
        title="Preferred suppliers"
        subtitle="Built from PO history and contracts (policy §6). Only Active suppliers are ranked."
        actions={<>
          <div><Label htmlFor="asof">As of</Label><Input id="asof" type="date" value={date} onChange={(e) => setAsOf(e.target.value)} className="h-9" /></div>
          <Button size="lg" className="self-end" disabled={!date} onClick={() => download(`/api/preferred-suppliers/export.csv?as_of=${date}&top=3`, `preferred_suppliers_${date}.csv`)}><Download className="h-4 w-4" /> Export CSV (top 3)</Button>
        </>}
      />
      <Notice className="mb-4"><Info className="mr-1 inline h-4 w-4" />
        Score = 0.30 × frequency (POs in 548 days vs the most-bought supplier) + 0.25 × recency (1 if bought within 90 days, 0.5 within a year) + 0.20 × contract held + 0.15 × on-time % + 0.10 × quality/5.
        Weights are part of the policy, so they are versioned and can be amended. Ties: most recent PO, then supplier ID.
      </Notice>
      <div className="grid gap-4 lg:grid-cols-[1fr_1.4fr]">
        <Card>
          <CardHeader><CardTitle>All items · top 3</CardTitle></CardHeader>
          {overview.isError ? <CardBody><ErrorBox error={overview.error} /></CardBody> : !overview.data ? <Spinner /> : (
            <div className="max-h-[70vh] overflow-auto">
              {overview.data!.map((o) => (
                <button key={o.item_code} onClick={() => setItem(o.item_code)} className={`block w-full border-b border-border px-3 py-2 text-left hover:bg-accent ${item === o.item_code ? "bg-primary/5" : ""}`}>
                  <div className="text-sm"><b>{o.item_code}</b> {o.description}</div>
                  <div className="text-xs text-muted-foreground">{o.suppliers.length ? o.suppliers.map((s) => `${s.rank}. ${s.supplier_id}`).join("  ") : "no eligible supplier"}</div>
                </button>
              ))}
            </div>
          )}
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>{detail.data ? `${detail.data.item.code} ${detail.data.item.description}` : "Item"}</CardTitle>
            <Select value={item} onChange={(e) => setItem(e.target.value)} className="h-8">{(overview.data ?? []).map((o) => <option key={o.item_code} value={o.item_code}>{o.item_code}</option>)}</Select>
          </CardHeader>
          <CardBody className="space-y-3">
            {detail.isError ? <ErrorBox error={detail.error} /> : !detail.data ? <Spinner /> : detail.data.ranked.length === 0 ? (
              <div className="text-sm text-muted-foreground">No Active supplier has bought or contracted this item in the lookback window.</div>
            ) : detail.data!.ranked.map((r) => (
              <div key={r.supplier_id} className="rounded-md border border-border p-3">
                <div className="flex items-center justify-between">
                  <div className="text-sm"><b className="mr-1">#{r.rank}</b>{r.supplier_id} {r.name}</div>
                  <div className="num text-right text-sm"><b>{Number(r.score).toFixed(3)}</b><div className="text-xs text-muted-foreground">ref {r.reference_price ? inr(r.reference_price, { paise: true }) : "—"} ({r.reference_ref})</div></div>
                </div>
                <div className="mt-2 grid grid-cols-5 gap-2">
                  {Object.entries(r.components).map(([k, v]) => (
                    <div key={k}><Bar value={Number(v)} max={Number(detail.data!.weights[k] ?? 0.3)} /><div className="mt-0.5 text-[11px] text-muted-foreground">{k.replace("_", "-")} {Number(v).toFixed(3)}</div></div>
                  ))}
                </div>
                <div className="mt-1.5 text-xs text-muted-foreground">{r.explanation}</div>
              </div>
            ))}
            {detail.data?.excluded.map((x) => <div key={x.supplier_id} className="text-xs text-muted-foreground">Excluded: {x.supplier_id} {x.name} <StatusBadge status={x.status} /> (policy 6.1, 5.7)</div>)}
            {detail.data && <div className="text-xs text-muted-foreground">Ranked under policy v{detail.data.policy_version} as of {detail.data.as_of}.</div>}
          </CardBody>
        </Card>
      </div>
    </div>
  );
}
