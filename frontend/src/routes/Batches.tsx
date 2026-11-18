import { useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, FileUp, Play, Radio } from "lucide-react";
import { api, download } from "@/lib/api";
import type { PolicyVersion, Run } from "@/lib/types";
import { dayTime, inrShort } from "@/lib/format";
import { Button, Card, CardBody, CardHeader, CardTitle, Empty, ErrorBox, Input, Label, Notice, PageHeader, RouteBadge, Select, Spinner } from "@/components/ui";

export default function BatchesPage() {
  const qc = useQueryClient();
  const nav = useNavigate();
  const fileRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState("");
  const [pin, setPin] = useState("");
  const [drag, setDrag] = useState(false);
  const runs = useQuery({ queryKey: ["runs"], queryFn: () => api.get<Run[]>("/api/runs") });
  const versions = useQuery({ queryKey: ["versions"], queryFn: () => api.get<PolicyVersion[]>("/api/policy/versions") });
  const approved = (versions.data ?? []).filter((v) => v.status === "ACTIVE" || v.status === "SUPERSEDED");

  const run = useMutation({
    mutationFn: () => {
      const params = new URLSearchParams({ format: "json", name: name || file?.name || "Batch" });
      if (pin) params.set("policy_version", pin);
      return api.upload<{ run_id: number }>(`/api/process-batch?${params}`, file!);
    },
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["runs"] });
      nav(`/batches/${r.run_id}`);
    },
  });

  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader title="Batches" subtitle="Upload a PR batch CSV, process it under the policy, and download the decisions." />
      <Card className="mb-6">
        <CardHeader><CardTitle>Process a PR batch</CardTitle></CardHeader>
        <CardBody className="grid gap-4 md:grid-cols-[1.4fr_1fr]">
          <div
            onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
            onDragLeave={() => setDrag(false)}
            onDrop={(e) => { e.preventDefault(); setDrag(false); const f = e.dataTransfer.files?.[0]; if (f) setFile(f); }}
            onClick={() => fileRef.current?.click()}
            className={`flex cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed p-6 text-center ${drag ? "border-primary bg-primary/5" : "border-border hover:border-primary/50"}`}
          >
            <FileUp className="mb-2 h-7 w-7 text-muted-foreground" />
            {file ? (
              <div className="text-sm"><span className="font-medium">{file.name}</span> · {(file.size / 1024).toFixed(1)} KB</div>
            ) : (
              <div className="text-sm text-muted-foreground">Drop a CSV here or click to choose (sample format: pr_no, pr_line, created_at, …)</div>
            )}
            <input ref={fileRef} type="file" accept=".csv,text/csv" className="hidden" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          </div>
          <div className="space-y-3">
            <div>
              <Label htmlFor="runname">Run name</Label>
              <Input id="runname" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Run 1 — blind batch (v5.0)" />
            </div>
            <div>
              <Label htmlFor="pin">Policy version</Label>
              <Select id="pin" value={pin} onChange={(e) => setPin(e.target.value)} className="w-full">
                <option value="">By effective date (each requirement uses the version in force on its date)</option>
                {approved.map((v) => (
                  <option key={v.version} value={v.version}>Pin to v{v.version} (from {v.effective_from})</option>
                ))}
              </Select>
              <p className="mt-1 text-xs text-muted-foreground">Pin v5.0 to reproduce Run 1 after an amendment is active.</p>
            </div>
            <Button className="w-full" size="lg" disabled={!file} loading={run.isPending} onClick={() => run.mutate()}>
              <Play className="h-4 w-4" /> Process batch
            </Button>
            {run.isError && <ErrorBox error={run.error} title="The batch could not be processed" />}
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardHeader><CardTitle>Runs</CardTitle></CardHeader>
        {runs.isLoading ? <Spinner /> : runs.isError ? <CardBody><ErrorBox error={runs.error} /></CardBody> : (runs.data ?? []).length === 0 ? (
          <CardBody><Empty title="No runs yet">Process a batch above.</Empty></CardBody>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-muted/60 text-xs text-muted-foreground">
                <tr>
                  {["Run", "Rows", "Requirements", "POs", "Routes", "Policy", "Created", ""].map((h) => (
                    <th key={h} className="px-3 py-2 text-left font-semibold">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {runs.data!.map((r) => (
                  <tr key={r.id} className="border-t border-border">
                    <td className="px-3 py-2">
                      <Link to={`/batches/${r.id}`} className="font-medium text-primary hover:underline">{r.name}</Link>
                      <div className="text-xs text-muted-foreground">#{r.id} · {r.kind === "LIVE" ? <span className="inline-flex items-center gap-1"><Radio className="h-3 w-3" />live</span> : r.input_file}</div>
                    </td>
                    <td className="num px-3 py-2">{r.summary.input_rows}{r.summary.not_processed ? <span className="text-xs text-muted-foreground"> ({r.summary.not_processed} not processed)</span> : null}</td>
                    <td className="num px-3 py-2">{r.summary.requirements} <span className="text-xs text-muted-foreground">· {inrShort(r.summary.total_value)}</span></td>
                    <td className="num px-3 py-2">{r.summary.purchase_orders}</td>
                    <td className="px-3 py-2">
                      <div className="flex max-w-xs flex-wrap gap-1">
                        {Object.entries(r.summary.routes_by_requirement ?? {}).map(([k, v]) => (
                          <span key={k} className="inline-flex items-center gap-1 text-xs"><RouteBadge route={k} /> <span className="num">{v}</span></span>
                        ))}
                      </div>
                    </td>
                    <td className="px-3 py-2 text-xs">{r.policy_pin ? <>pinned v{r.policy_pin}</> : <>v{(r.summary.policy_versions_used ?? []).join(", v")}</>}</td>
                    <td className="px-3 py-2 text-xs text-muted-foreground">{dayTime(r.created_at)}<br />by {r.created_by}</td>
                    <td className="px-3 py-2 text-right">
                      <Button size="sm" variant="secondary" onClick={() => download(`/api/runs/${r.id}/export.csv`, `decisions_run${r.id}.csv`)}>
                        <Download className="h-3.5 w-3.5" /> CSV
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      <Notice className="mt-4">
        API: <code className="text-xs">curl -F file=@batch.csv "&lt;host&gt;/api/process-batch?format=csv&amp;policy_version=5.0"</code> returns the same CSV.
      </Notice>
    </div>
  );
}
