import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FilePlus2, GitCompare, History, Info, ScrollText } from "lucide-react";
import { api } from "@/lib/api";
import type { Amendment, FactInfo, PolicyVersion } from "@/lib/types";
import { dayTime, day } from "@/lib/format";
import { useUser } from "@/lib/user";
import { WelcomePanel } from "@/components/Layout";
import {
  Badge, Button, Card, CardBody, CardHeader, CardTitle, Dialog, DialogContent, DialogTrigger, Empty, ErrorBox, Input, Notice,
  PageHeader, Select, Spinner, StatusBadge, Tabs,
} from "@/components/ui";

export default function PolicyPage() {
  const nav = useNavigate();
  const { role } = useUser();
  const versions = useQuery({ queryKey: ["versions"], queryFn: () => api.get<PolicyVersion[]>("/api/policy/versions") });
  const amendments = useQuery({ queryKey: ["amendments"], queryFn: () => api.get<Amendment[]>("/api/policy/amendments") });
  const approved = (versions.data ?? []).filter((v) => v.status === "ACTIVE" || v.status === "SUPERSEDED");
  const active = approved.find((v) => v.status === "ACTIVE") ?? approved[approved.length - 1];
  const [selected, setSelected] = useState<string>("");
  const [tab, setTab] = useState<"rules" | "params" | "diff" | "facts">("rules");
  const shown = selected || active?.version || "";
  const detail = useQuery({
    queryKey: ["version", shown],
    queryFn: () => api.get<PolicyVersion>(`/api/policy/versions/${shown}`),
    enabled: !!shown,
  });

  return (
    <div className="mx-auto max-w-6xl">
      <WelcomePanel />
      <PageHeader
        title="Policy"
        subtitle="The policy is versioned data. Each requirement is decided by the version in force on its requirement date."
        actions={
          <Button size="lg" onClick={() => nav("/policy/amendments/new")} disabled={role === "REQUESTER"}>
            <FilePlus2 className="h-4 w-4" /> Propose amendment
          </Button>
        }
      />
      {role === "REQUESTER" && <Notice className="mb-4">Switch to Meera (procurement admin) to propose and approve amendments.</Notice>}

      <Card className="mb-5">
        <CardHeader><CardTitle className="flex items-center gap-2"><History className="h-4 w-4" /> Versions</CardTitle></CardHeader>
        <CardBody>
          {versions.isLoading ? <Spinner /> : versions.isError ? <ErrorBox error={versions.error} /> : (
            <ol className="relative flex flex-wrap gap-3">
              {(versions.data ?? []).filter((v) => v.status !== "DRAFT").map((v) => (
                <li key={v.id}>
                  <button
                    onClick={() => setSelected(v.version)}
                    className={`min-w-[190px] rounded-lg border p-3 text-left ${shown === v.version ? "border-primary ring-2 ring-primary/20" : "border-border hover:border-primary/40"}`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-semibold">v{v.version}</span>
                      <StatusBadge status={v.status} />
                    </div>
                    <div className="mt-1 text-xs text-muted-foreground">effective {day(v.effective_from)}</div>
                    <div className="text-xs text-muted-foreground">{v.approved_by ? `approved by ${v.approved_by}` : `created by ${v.created_by}`}</div>
                  </button>
                </li>
              ))}
            </ol>
          )}
          {approved.length > 1 && (
            <p className="mt-3 text-xs text-muted-foreground">
              Older versions stay in force for requirements dated before a newer version's effective date. A batch can be pinned to one version from the Batches page.
            </p>
          )}
        </CardBody>
      </Card>

      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <Tabs value={tab} onChange={setTab} items={[
          { value: "rules", label: "Rules (plain language)" },
          { value: "params", label: "Parameters" },
          { value: "diff", label: "Compare versions" },
          { value: "facts", label: "Facts & operators" },
        ]} />
        {detail.data && <div className="text-xs text-muted-foreground">Showing v{detail.data.version} · {detail.data.policy_id}</div>}
      </div>

      {tab === "rules" && (detail.isLoading ? <Spinner /> : detail.data && (
        <Card>
          <div className="divide-y divide-border">
            {detail.data.rules!.map((r, i) => (
              <div key={r.id} className="flex gap-4 px-4 py-3">
                <div className="w-20 shrink-0">
                  <div className="text-xs text-muted-foreground">#{i + 1}</div>
                  <div className="font-mono text-xs">{r.id}</div>
                  <Badge className="mt-1 bg-slate-50 text-slate-600 ring-slate-500/20">§{r.clause}</Badge>
                </div>
                <div className="flex-1">
                  <div className="text-sm font-medium">{r.name}{r.enabled === "no" && <span className="ml-2 text-xs text-muted-foreground">(disabled)</span>}</div>
                  <div className="mt-0.5 text-sm text-muted-foreground">{r.text}</div>
                </div>
              </div>
            ))}
          </div>
          {(detail.data.lint ?? []).length > 0 && (
            <CardBody className="border-t border-border">
              {detail.data.lint!.map((l) => <div key={l} className="text-xs text-amber-700">⚠ {l}</div>)}
            </CardBody>
          )}
          <CardBody className="border-t border-border text-xs text-muted-foreground">
            Rules are evaluated top to bottom; the first rule whose condition holds (and whose outcome can be fulfilled) decides (policy §5).
          </CardBody>
        </Card>
      ))}

      {tab === "params" && detail.data && (
        <Card>
          <table className="w-full text-sm">
            <thead className="bg-muted/60 text-xs text-muted-foreground">
              <tr><th className="px-3 py-2 text-left">Parameter</th><th className="px-3 py-2 text-left">Name</th><th className="px-3 py-2 text-right">Value</th><th className="px-3 py-2 text-left">Clause</th></tr>
            </thead>
            <tbody>
              {detail.data.params!.map((p) => (
                <tr key={p.name} className="border-t border-border">
                  <td className="px-3 py-2">{p.label}</td>
                  <td className="px-3 py-2 font-mono text-xs">{p.name}</td>
                  <td className="num px-3 py-2 text-right font-medium">{p.unit === "INR" ? `₹${Number(p.value).toLocaleString("en-IN")}` : `${p.value} ${p.unit}`}</td>
                  <td className="px-3 py-2">§{p.clause}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      {tab === "diff" && <VersionDiff versions={(versions.data ?? []).filter((v) => v.status !== "DRAFT").map((v) => v.version)} />}
      {tab === "facts" && <FactsHelp />}

      <Card className="mt-6">
        <CardHeader><CardTitle className="flex items-center gap-2"><ScrollText className="h-4 w-4" /> Amendments</CardTitle></CardHeader>
        {amendments.isLoading ? <Spinner /> : (amendments.data ?? []).length === 0 ? (
          <CardBody><Empty title="No amendments yet">Upload an amendment document, describe a change, or use the structured editor.</Empty></CardBody>
        ) : (
          <div className="divide-y divide-border">
            {amendments.data!.map((a) => (
              <Link key={a.id} to={`/policy/amendments/${a.id}`} className="flex items-center gap-3 px-4 py-3 hover:bg-accent">
                <StatusBadge status={a.status} />
                <div className="flex-1">
                  <div className="text-sm font-medium">{a.title}</div>
                  <div className="text-xs text-muted-foreground">
                    #{a.id} · {a.source_kind === "DOC" ? `document ${a.source_filename ?? ""}` : a.source_kind === "CHAT" ? "described in words" : "structured editor"} ·
                    {" "}v{a.base_version} → v{a.proposed_version} · effective {day(a.effective_from)} · {a.created_by}, {dayTime(a.created_at)}
                  </div>
                </div>
                {a.impact?.summary && <span className="text-xs text-muted-foreground">{a.impact.summary.lines_changed} line(s) change</span>}
              </Link>
            ))}
          </div>
        )}
      </Card>
      {role === "PROCUREMENT_ADMIN" && active && approved.length > 1 && <RetireBox version={active.version} />}
    </div>
  );
}

function VersionDiff({ versions }: { versions: string[] }) {
  const [from, setFrom] = useState(versions[0] ?? "");
  const [to, setTo] = useState(versions[versions.length - 1] ?? "");
  const diff = useQuery({
    queryKey: ["diff", from, to],
    queryFn: () => api.get<{ changes: { op: string; text: string }[] }>(`/api/policy/diff?from=${from}&to=${to}`),
    enabled: !!from && !!to && from !== to,
  });
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2 text-sm">
          <GitCompare className="h-4 w-4" />
          <Select value={from} onChange={(e) => setFrom(e.target.value)}>{versions.map((v) => <option key={v}>{v}</option>)}</Select>
          →
          <Select value={to} onChange={(e) => setTo(e.target.value)}>{versions.map((v) => <option key={v}>{v}</option>)}</Select>
        </div>
      </CardHeader>
      <CardBody>
        {from === to ? <div className="text-sm text-muted-foreground">Choose two different versions.</div> : diff.isLoading ? <Spinner /> : diff.isError ? <ErrorBox error={diff.error} /> : (
          (diff.data?.changes ?? []).length === 0 ? <div className="text-sm text-muted-foreground">No differences.</div> : (
            <ul className="space-y-2">
              {diff.data!.changes.map((c, i) => (
                <li key={i} className="flex gap-2 text-sm"><Badge className="shrink-0 bg-slate-50 text-slate-600 ring-slate-500/20">{c.op}</Badge>{c.text}</li>
              ))}
            </ul>
          )
        )}
      </CardBody>
    </Card>
  );
}

function FactsHelp() {
  const facts = useQuery({ queryKey: ["facts"], queryFn: () => api.get<{ facts: FactInfo[]; ops: string[] }>("/api/policy/facts") });
  if (facts.isLoading) return <Spinner />;
  return (
    <Card>
      <CardBody className="text-sm">
        <Notice className="mb-3"><Info className="mr-1 inline h-4 w-4" />Conditions in rules are written over these facts. A new kind of rule needs no code as long as it uses these facts; a new fact is one small function in the engine.</Notice>
        <table className="w-full text-sm">
          <thead className="text-xs text-muted-foreground"><tr><th className="py-1 text-left">Fact</th><th className="text-left">Type</th><th className="text-left">Meaning</th></tr></thead>
          <tbody>
            {facts.data!.facts.map((f) => (
              <tr key={f.name} className="border-t border-border">
                <td className="py-1.5 font-mono text-xs">{f.name}</td><td className="text-xs">{f.type}</td><td className="text-xs text-muted-foreground">{f.description}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </CardBody>
    </Card>
  );
}

function RetireBox({ version }: { version: string }) {
  const qc = useQueryClient();
  const [reason, setReason] = useState("");
  const m = useMutation({
    mutationFn: () => api.post(`/api/policy/versions/${version}/retire`, { reason }),
    onSuccess: () => qc.invalidateQueries(),
  });
  return (
    <Dialog>
      <DialogTrigger asChild>
        <button className="mt-3 text-xs text-muted-foreground underline">Retire v{version} (revert to the previous version)…</button>
      </DialogTrigger>
      <DialogContent title={`Retire v${version}`} description="The version stops being used for new runs. History and audit records are kept.">
        <Input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Reason (required)" />
        {m.isError && <div className="mt-2"><ErrorBox error={m.error} /></div>}
        <div className="mt-3 flex justify-end"><Button variant="destructive" disabled={!reason} loading={m.isPending} onClick={() => m.mutate()}>Retire version</Button></div>
      </DialogContent>
    </Dialog>
  );
}
