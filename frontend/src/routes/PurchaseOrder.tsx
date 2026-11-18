import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Printer, Send } from "lucide-react";
import { api } from "@/lib/api";
import type { PO } from "@/lib/types";
import { dayTime, inr, qty } from "@/lib/format";
import { Button, Card, CardBody, ErrorBox, PageHeader, RouteBadge, Spinner, StatusBadge } from "@/components/ui";

export default function POPage() {
  const { id } = useParams();
  const qc = useQueryClient();
  const po = useQuery({ queryKey: ["po", id], queryFn: () => api.get<PO>(`/api/purchase-orders/${id}`) });
  const approve = useMutation({ mutationFn: () => api.post(`/api/purchase-orders/${id}/approve`), onSuccess: () => qc.invalidateQueries() });
  const issue = useMutation({ mutationFn: () => api.post(`/api/purchase-orders/${id}/issue`), onSuccess: () => qc.invalidateQueries() });
  if (po.isLoading) return <Spinner />;
  if (po.isError) return <ErrorBox error={po.error} />;
  const p = po.data!;
  return (
    <div className="mx-auto max-w-4xl">
      <PageHeader
        title={`Purchase order ${p.code}`}
        subtitle={<span className="flex items-center gap-2"><StatusBadge status={p.status} /><RouteBadge route={p.route} /> policy v{p.policy_version} · run #{p.run_id}</span>}
        actions={<>
          <Button variant="secondary" onClick={() => window.print()}><Printer className="h-4 w-4" /> Print</Button>
          {p.status === "PROPOSED" && <Button loading={approve.isPending} onClick={() => approve.mutate()}><CheckCircle2 className="h-4 w-4" /> Approve all lines</Button>}
          {p.status === "APPROVED" && <Button variant="success" loading={issue.isPending} onClick={() => issue.mutate()}><Send className="h-4 w-4" /> Mark issued</Button>}
        </>}
      />
      {(approve.isError || issue.isError) && <ErrorBox error={approve.error ?? issue.error} />}
      <Card>
        <CardBody>
          <div className="mb-5 grid grid-cols-2 gap-4 text-sm">
            <div><div className="text-xs text-muted-foreground">Supplier</div><div className="font-medium">{p.supplier_id} · {p.supplier_name}</div><div className="text-muted-foreground">{p.supplier_city}</div></div>
            <div><div className="text-xs text-muted-foreground">Deliver to</div><div className="font-medium">{p.plant} · {p.plant_name}</div><div className="text-muted-foreground">Corvo Engineering Pvt Ltd</div></div>
          </div>
          <table className="w-full text-sm">
            <thead className="border-b border-border text-xs text-muted-foreground"><tr>{["#", "Item", "Requirement / PR lines", "Qty", "Unit price", "Amount", ""].map((h) => <th key={h} className="py-2 text-left">{h}</th>)}</tr></thead>
            <tbody>
              {p.lines.map((l, i) => (
                <tr key={l.requirement_id} className="border-b border-border/60 align-top">
                  <td className="py-2">{i + 1}</td>
                  <td className="py-2"><div className="font-medium">{l.item_code}</div><div className="text-xs text-muted-foreground">{l.description}</div></td>
                  <td className="py-2 text-xs"><Link to={`/requirements/${l.requirement_id}`} className="text-primary hover:underline">{l.group_code}</Link><div className="text-muted-foreground">{l.pr_lines.join(", ")}</div></td>
                  <td className="num py-2">{qty(l.qty)} {l.uom}</td>
                  <td className="num py-2">{inr(l.unit_price, { paise: true })}</td>
                  <td className="num py-2 font-medium">{inr(l.amount)}</td>
                  <td className="py-2"><StatusBadge status={l.status} /></td>
                </tr>
              ))}
            </tbody>
            <tfoot><tr><td colSpan={5} className="py-3 text-right font-medium">Total (excl. GST)</td><td className="num py-3 text-base font-semibold">{inr(p.total)}</td><td /></tr></tfoot>
          </table>
          <div className="mt-4 text-xs text-muted-foreground">Created {dayTime(p.created_at)}{p.issued_at && ` · issued ${dayTime(p.issued_at)}`}. Requirements were combined because they share supplier, plant and route and were raised within the consolidation window (policy §7).</div>
        </CardBody>
      </Card>
    </div>
  );
}
