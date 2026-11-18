import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FilePlus2, FileSearch, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import type { Contract } from "@/lib/types";
import { day, inr, inrShort } from "@/lib/format";
import {
  Badge, Bar, Button, Card, Dialog, DialogContent, DialogTrigger, ErrorBox, Input, Label, Notice,
  PageHeader, Spinner, StatusBadge,
} from "@/components/ui";

interface Form {
  contract_id: string; supplier_id: string; supplier_name: string; start_date: string; end_date: string; value_cap: string;
  plants: string[]; lines: { item_code: string; description: string; uom: string; rate: string }[];
}

export default function ContractsPage() {
  const contracts = useQuery({ queryKey: ["contracts"], queryFn: () => api.get<Contract[]>("/api/contracts") });
  const recon = useQuery({ queryKey: ["reconcile"], queryFn: () => api.get<{ matched: string[]; pdf_only: string[]; mismatches: { contract_id: string; field: string; register_value: string; pdf_value: string }[]; without_pdf: string[] }>("/api/contracts/reconcile") });
  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader title="Contracts" subtitle="Rate contract register (as at 31 Oct 2026) plus contracts that exist only as signed PDFs (policy 4.4)." actions={<AddFromPdf />} />
      {recon.data && (
        <Notice tone={recon.data.mismatches.length ? "warn" : "ok"} className="mb-4">
          Reconciliation: {recon.data.matched.length} register contracts match their signed PDFs field by field
          {recon.data.mismatches.length > 0 && <>; <b>{recon.data.mismatches.length} mismatch(es)</b>: {recon.data.mismatches.map((m) => `${m.contract_id} ${m.field} ${m.register_value}≠${m.pdf_value}`).join("; ")}</>}
          {recon.data.pdf_only.length > 0 && <> · PDF-only contracts (consumed starts at ₹0): <b>{recon.data.pdf_only.join(", ")}</b></>}
          {recon.data.without_pdf.length > 0 && <> · no signed copy stored: {recon.data.without_pdf.join(", ")}</>}
        </Notice>
      )}
      {contracts.isLoading ? <Spinner /> : contracts.isError ? <ErrorBox error={contracts.error} /> : (
        <Card>
          <table className="w-full text-sm">
            <thead className="bg-muted/60 text-xs text-muted-foreground"><tr>{["Contract", "Supplier", "Validity", "Ceiling used", "Items & rates", "Source"].map((h) => <th key={h} className="px-3 py-2 text-left">{h}</th>)}</tr></thead>
            <tbody>
              {contracts.data!.map((c) => {
                const cap = Number(c.value_cap); const used = Number(c.consumed_live);
                const pct = used / cap;
                return (
                  <tr key={c.id} className="border-t border-border align-top">
                    <td className="px-3 py-2 font-medium">{c.id}{c.has_pdf && <a href={`/api/contracts/${c.id}/pdf`} target="_blank" rel="noreferrer" className="ml-1 text-xs font-normal text-primary hover:underline">PDF</a>}</td>
                    <td className="px-3 py-2">{c.supplier_id} {c.supplier_name}<div><StatusBadge status={c.supplier_status} />{c.supplier_status !== "Active" && <span className="ml-1 text-xs text-red-700">not applicable (4.1)</span>}</div></td>
                    <td className="whitespace-nowrap px-3 py-2 text-xs">{day(c.start_date)} – {day(c.end_date)}<div><StatusBadge status={c.validity} /></div></td>
                    <td className="w-56 px-3 py-2">
                      <Bar value={used} max={cap} tone={pct > 0.9 ? "bg-red-500" : pct > 0.7 ? "bg-amber-500" : "bg-emerald-500"} />
                      <div className="num mt-1 text-xs text-muted-foreground">{inrShort(used)} of {inrShort(cap)} · <b className="text-foreground">{inr(Number(c.remaining))}</b> left</div>
                      {Number(c.committed_live) > 0 && <div className="text-xs text-muted-foreground">incl. {inr(c.committed_live)} approved in the app</div>}
                    </td>
                    <td className="px-3 py-2 text-xs">{c.lines.map((l) => <div key={l.item_code}>{l.item_code} {l.description} · <span className="num">{inr(l.rate, { paise: true })}</span>/{l.uom}</div>)}</td>
                    <td className="px-3 py-2"><Badge className={c.source === "PDF" ? "bg-violet-50 text-violet-700 ring-violet-600/20" : "bg-slate-50 text-slate-600 ring-slate-500/20"}>{c.source === "PDF" ? "PDF only" : "Register"}</Badge></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}

function AddFromPdf() {
  const qc = useQueryClient();
  const ref = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [form, setForm] = useState<Form | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [errors, setErrors] = useState<string[]>([]);
  const [open, setOpen] = useState(false);
  const extract = useMutation({
    mutationFn: (f: File) => api.upload<{ form: Form; warnings: string[]; errors: string[] }>("/api/contracts/import-pdf", f),
    onSuccess: (r) => { setForm(r.form); setWarnings(r.warnings); setErrors(r.errors); },
  });
  const save = useMutation({
    mutationFn: async () => {
      const fd = new FormData();
      fd.append("file", file!);
      fd.append("form", JSON.stringify(form));
      const res = await fetch("/api/contracts", { method: "POST", headers: { "X-User": localStorage.getItem("corvo.user") || "Rahul" }, body: fd });
      if (!res.ok) throw new Error((await res.json()).detail);
      return res.json();
    },
    onSuccess: () => { qc.invalidateQueries(); setOpen(false); setForm(null); setFile(null); },
  });
  const upd = (k: keyof Form, v: string) => setForm((f) => (f ? { ...f, [k]: v } : f));
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild><Button size="lg"><FilePlus2 className="h-4 w-4" /> Add contract from PDF</Button></DialogTrigger>
      <DialogContent title="Add a contract from its signed PDF" description="Fields are read from the PDF; check them before saving. A PDF-only contract starts with ₹0 consumed (4.2)." className="max-w-2xl">
        {!form ? (
          <div className="space-y-3">
            <div onClick={() => ref.current?.click()} className="cursor-pointer rounded-lg border-2 border-dashed border-border p-8 text-center text-sm text-muted-foreground hover:border-primary/50">
              <FileSearch className="mx-auto mb-2 h-6 w-6" />{file ? file.name : "Choose the signed contract PDF"}
              <input ref={ref} type="file" accept="application/pdf" className="hidden" onChange={(e) => { const f = e.target.files?.[0]; if (f) { setFile(f); extract.mutate(f); } }} />
            </div>
            {extract.isPending && <Spinner label="Reading the PDF…" />}
            {extract.isError && <ErrorBox error={extract.error} />}
          </div>
        ) : (
          <div className="space-y-3">
            {warnings.map((w) => <Notice key={w} tone="warn">{w}</Notice>)}
            {errors.map((e) => <Notice key={e} tone="warn"><b>Must fix:</b> {e}</Notice>)}
            <div className="grid gap-2 sm:grid-cols-3">
              <div><Label>Contract no.</Label><Input value={form.contract_id} onChange={(e) => upd("contract_id", e.target.value)} /></div>
              <div><Label>Supplier ID</Label><Input value={form.supplier_id} onChange={(e) => upd("supplier_id", e.target.value)} /></div>
              <div><Label>Supplier name</Label><Input value={form.supplier_name} onChange={(e) => upd("supplier_name", e.target.value)} /></div>
              <div><Label>Valid from</Label><Input type="date" value={form.start_date} onChange={(e) => upd("start_date", e.target.value)} /></div>
              <div><Label>Valid to</Label><Input type="date" value={form.end_date} onChange={(e) => upd("end_date", e.target.value)} /></div>
              <div><Label>Value ceiling (₹)</Label><Input value={form.value_cap} onChange={(e) => upd("value_cap", e.target.value)} /></div>
            </div>
            <div className="text-xs text-muted-foreground">Plants: {form.plants.join(", ") || "all"}</div>
            <table className="w-full text-sm">
              <thead className="text-xs text-muted-foreground"><tr><th className="text-left">Item</th><th className="text-left">Description</th><th className="text-left">UoM</th><th className="text-left">Rate</th><th /></tr></thead>
              <tbody>
                {form.lines.map((l, i) => (
                  <tr key={i}>
                    {(["item_code", "description", "uom", "rate"] as const).map((k) => (
                      <td key={k} className="pr-1 py-0.5"><Input className="h-8" value={l[k]} onChange={(e) => setForm({ ...form, lines: form.lines.map((x, j) => (j === i ? { ...x, [k]: e.target.value } : x)) })} /></td>
                    ))}
                    <td><button aria-label="Remove line" onClick={() => setForm({ ...form, lines: form.lines.filter((_, j) => j !== i) })}><Trash2 className="h-4 w-4 text-muted-foreground" /></button></td>
                  </tr>
                ))}
              </tbody>
            </table>
            {save.isError && <ErrorBox error={save.error} />}
            <div className="flex justify-between">
              <Button variant="ghost" onClick={() => { setForm(null); setFile(null); }}>Choose another PDF</Button>
              <Button loading={save.isPending} onClick={() => save.mutate()}>Save contract</Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

