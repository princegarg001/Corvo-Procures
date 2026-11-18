import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { FileText, MessageSquareText, SlidersHorizontal, Upload } from "lucide-react";
import { api } from "@/lib/api";
import type { Amendment } from "@/lib/types";
import { useMeta } from "@/components/Layout";
import { OpsEditor, type Op } from "@/components/OpsEditor";
import { Button, Card, CardBody, ErrorBox, Input, Label, Notice, PageHeader, Tabs, Textarea } from "@/components/ui";

export default function AmendmentNewPage() {
  const nav = useNavigate();
  const meta = useMeta();
  const [tab, setTab] = useState<"doc" | "text" | "editor">("doc");
  const [file, setFile] = useState<File | null>(null);
  const [text, setText] = useState("");
  const [title, setTitle] = useState("");
  const [eff, setEff] = useState("");
  const [ops, setOps] = useState<Op[]>([]);
  const fileRef = useRef<HTMLInputElement>(null);

  const submit = useMutation({
    mutationFn: async () => {
      if (tab === "doc") return api.upload<Amendment>("/api/policy/amendments", file!, { title, ...(eff ? { effective_from: eff } : {}) });
      if (tab === "text") return api.post<Amendment>("/api/policy/amendments", { text, title, effective_from: eff || null });
      return api.post<Amendment>("/api/policy/amendments", { ops, title, effective_from: eff || null });
    },
    onSuccess: (a) => nav(`/policy/amendments/${a.id}`),
  });

  const ready = tab === "doc" ? !!file : tab === "text" ? text.trim().length > 10 : ops.length > 0 && !!eff;
  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader title="Propose a policy amendment" subtitle="Nothing changes until you review the plain-language changes and their impact, and approve." />
      <div className="mb-4">
        <Tabs value={tab} onChange={setTab} items={[
          { value: "doc", label: <span className="inline-flex items-center gap-1.5"><FileText className="h-4 w-4" /> Upload document</span> },
          { value: "text", label: <span className="inline-flex items-center gap-1.5"><MessageSquareText className="h-4 w-4" /> Describe the change</span> },
          { value: "editor", label: <span className="inline-flex items-center gap-1.5"><SlidersHorizontal className="h-4 w-4" /> Structured editor</span> },
        ]} />
      </div>
      {meta.data && !meta.data.llm_available && tab !== "editor" && (
        <Notice tone="warn" className="mb-4">
          No AI provider is configured, so the text is read by the deterministic reader: it handles limit / window / date / supplier / weight changes;
          for new rules it will ask you to use the structured editor.
        </Notice>
      )}
      <Card className="mb-4">
        <CardBody className="grid gap-3 sm:grid-cols-[2fr_1fr]">
          <div><Label>Title (optional)</Label><Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Amendment 1 — spot limit" /></div>
          <div>
            <Label>Effective from {tab === "editor" ? "(required)" : "(optional: overrides the date in the text)"}</Label>
            <Input type="date" value={eff} onChange={(e) => setEff(e.target.value)} />
          </div>
        </CardBody>
      </Card>

      {tab === "doc" && (
        <Card>
          <CardBody>
            <div onClick={() => fileRef.current?.click()} className="flex cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed border-border p-10 text-center hover:border-primary/50">
              <Upload className="mb-2 h-7 w-7 text-muted-foreground" />
              {file ? <div className="text-sm font-medium">{file.name}</div> : <div className="text-sm text-muted-foreground">PDF, Word (.docx), .txt or .md amendment document</div>}
              <input ref={fileRef} type="file" className="hidden" accept=".pdf,.docx,.txt,.md,text/plain,application/pdf" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
            </div>
          </CardBody>
        </Card>
      )}
      {tab === "text" && (
        <Card>
          <CardBody>
            <Label>Describe the change in your own words</Label>
            <Textarea className="h-40" value={text} onChange={(e) => setText(e.target.value)}
              placeholder="e.g. From 1 December 2026 the spot purchase limit goes up to ₹3 lakh. For Chakan only, emergency purchases up to ₹7.5 lakh can go to the preferred supplier." />
          </CardBody>
        </Card>
      )}
      {tab === "editor" && <OpsEditor ops={ops} onChange={setOps} />}

      <div className="mt-4 flex items-center justify-end gap-3">
        {submit.isError && <div className="flex-1"><ErrorBox error={submit.error} /></div>}
        <Button size="lg" disabled={!ready} loading={submit.isPending} onClick={() => submit.mutate()}>
          {tab === "editor" ? "Review changes & impact" : "Read amendment & review"}
        </Button>
      </div>
    </div>
  );
}
