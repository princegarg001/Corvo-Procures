import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import type { FactInfo, PolicyVersion } from "@/lib/types";
import { Badge, Button, Card, CardBody, CardHeader, CardTitle, Input, Label, Select, Textarea } from "@/components/ui";

export type Op = Record<string, unknown>;

const OP_TYPES: { value: string; label: string }[] = [
  { value: "set_param", label: "Change a limit / window / number" },
  { value: "add_rule", label: "Add a rule (new condition, plant/category rule, new route)" },
  { value: "modify_rule", label: "Modify a rule's outcome" },
  { value: "remove_rule", label: "Remove a rule" },
  { value: "add_param", label: "Add a parameter" },
  { value: "add_item_set", label: "Define an item set (e.g. OEM items)" },
  { value: "set_supplier_override", label: "Block / unblock a supplier" },
  { value: "set_ranking", label: "Change ranking weights" },
  { value: "set_consolidation", label: "Change PO consolidation" },
  { value: "set_clubbing", label: "Turn clubbing on / off" },
];

interface PolicyBody {
  params: Record<string, { value: number; unit: string; label: string; clause: string }>;
  rules: { id: string; name: string; clause: string; then: { route: string; decision: string; suggest?: number; supplier?: string; price?: string } }[];
  preferred_suppliers: { weights: Record<string, number> };
  consolidation: { exclude_routes: string[] };
  clubbing: { enabled: boolean };
  item_sets: Record<string, unknown>;
}

export function OpsEditor({ ops, onChange }: { ops: Op[]; onChange: (ops: Op[]) => void }) {
  const active = useQuery({ queryKey: ["policy-active"], queryFn: () => api.get<PolicyVersion>("/api/policy/active") });
  const facts = useQuery({ queryKey: ["facts"], queryFn: () => api.get<{ facts: FactInfo[] }>("/api/policy/facts") });
  const suppliers = useQuery({ queryKey: ["suppliers"], queryFn: () => api.get<{ id: string; name: string; status: string }[]>("/api/suppliers") });
  const plants = useQuery({ queryKey: ["plants"], queryFn: () => api.get<{ code: string; name: string }[]>("/api/plants") });
  const items = useQuery({ queryKey: ["items"], queryFn: () => api.get<{ code: string; category: string; type: string }[]>("/api/items") });
  const body = active.data?.body as unknown as PolicyBody | undefined;
  const [type, setType] = useState("set_param");
  const [json, setJson] = useState(JSON.stringify(ops, null, 2));
  const [jsonErr, setJsonErr] = useState("");
  useEffect(() => setJson(JSON.stringify(ops, null, 2)), [ops]);

  const add = (op: Op) => onChange([...ops, op]);
  const ctx = {
    body, facts: facts.data?.facts ?? [], suppliers: suppliers.data ?? [], plants: plants.data ?? [],
    categories: [...new Set((items.data ?? []).map((i) => i.category))].sort(),
    types: [...new Set((items.data ?? []).map((i) => i.type))].sort(),
  };

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader><CardTitle>Add a change</CardTitle></CardHeader>
        <CardBody className="space-y-3">
          <Select value={type} onChange={(e) => setType(e.target.value)} className="w-full">
            {OP_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
          </Select>
          {!body ? <div className="text-sm text-muted-foreground">Loading the active policy…</div> : <OpForm key={type} type={type} ctx={ctx} onAdd={add} />}
        </CardBody>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Changes ({ops.length})</CardTitle>
          {ops.length > 0 && <Button size="sm" variant="ghost" onClick={() => onChange([])}>Clear</Button>}
        </CardHeader>
        <CardBody className="space-y-2">
          {ops.length === 0 && <div className="text-sm text-muted-foreground">No changes yet. Add one on the left, or paste ops JSON below.</div>}
          {ops.map((op, i) => (
            <div key={i} className="flex items-start gap-2 rounded-md border border-border p-2 text-xs">
              <Badge className="bg-slate-50 text-slate-700 ring-slate-500/20">{String(op.op)}</Badge>
              <code className="flex-1 break-all text-[11px] text-muted-foreground">{JSON.stringify({ ...op, op: undefined })}</code>
              <button onClick={() => onChange(ops.filter((_, j) => j !== i))} aria-label="Remove change" className="text-muted-foreground hover:text-red-600"><Trash2 className="h-3.5 w-3.5" /></button>
            </div>
          ))}
          <details className="pt-2">
            <summary className="cursor-pointer text-xs font-medium text-muted-foreground">Live JSON (editable)</summary>
            <Textarea
              className="mt-2 h-64 font-mono text-xs"
              value={json}
              onChange={(e) => {
                setJson(e.target.value);
                try {
                  const parsed = JSON.parse(e.target.value);
                  if (!Array.isArray(parsed)) throw new Error("must be a JSON array of ops");
                  setJsonErr("");
                  onChange(parsed);
                } catch (err) {
                  setJsonErr((err as Error).message);
                }
              }}
            />
            {jsonErr && <div className="text-xs text-red-600">{jsonErr}</div>}
          </details>
        </CardBody>
      </Card>
    </div>
  );
}

interface Ctx {
  body?: PolicyBody;
  facts: FactInfo[];
  suppliers: { id: string; name: string; status: string }[];
  plants: { code: string; name: string }[];
  categories: string[];
  types: string[];
}

function OpForm({ type, ctx, onAdd }: { type: string; ctx: Ctx; onAdd: (op: Op) => void }) {
  const body = ctx.body!;
  const ruleIds = body.rules.map((r) => r.id);
  const routes = [...new Set(body.rules.map((r) => r.then.route))];
  const [f, setF] = useState<Record<string, string>>({});
  const set = (k: string) => (e: { target: { value: string } }) => setF((s) => ({ ...s, [k]: e.target.value }));
  const field = (k: string, label: string, ph = "", t = "text") => (
    <div><Label>{label}</Label><Input type={t} value={f[k] ?? ""} onChange={set(k)} placeholder={ph} /></div>
  );

  if (type === "set_param") {
    const p = body.params[f.name ?? ""];
    return (
      <div className="space-y-3">
        <div><Label>Parameter</Label>
          <Select className="w-full" value={f.name ?? ""} onChange={set("name")}>
            <option value="">Choose…</option>
            {Object.entries(body.params).map(([k, v]) => <option key={k} value={k}>{v.label} (§{v.clause}) — now {v.unit === "INR" ? "₹" + v.value.toLocaleString("en-IN") : `${v.value} ${v.unit}`}</option>)}
          </Select>
        </div>
        {field("value", `New value${p ? ` (${p.unit})` : ""}`, "e.g. 300000")}
        <Button disabled={!f.name || !f.value} onClick={() => onAdd({ op: "set_param", name: f.name, value: f.value })}><Plus className="h-4 w-4" /> Add change</Button>
      </div>
    );
  }
  if (type === "add_param") {
    return (
      <div className="grid gap-3 sm:grid-cols-2">
        {field("name", "Name (snake_case)", "chk1_emergency_limit")}
        {field("label", "Label", "Emergency PO limit (Chakan)")}
        <div><Label>Unit</Label><Select className="w-full" value={f.unit ?? "INR"} onChange={set("unit")}>{["INR", "days", "hours", "%", ""].map((u) => <option key={u} value={u}>{u || "(none)"}</option>)}</Select></div>
        {field("value", "Value", "750000")}
        {field("clause", "Clause", "5.3A")}
        <div className="flex items-end"><Button disabled={!f.name || !f.value} onClick={() => onAdd({ op: "add_param", name: f.name, value: f.value, unit: f.unit ?? "INR", label: f.label ?? "", clause: f.clause ?? "" })}><Plus className="h-4 w-4" /> Add</Button></div>
      </div>
    );
  }
  if (type === "add_rule") return <AddRuleForm ctx={ctx} ruleIds={ruleIds} routes={routes} onAdd={onAdd} />;
  if (type === "modify_rule") {
    const rule = body.rules.find((r) => r.id === f.rule_id);
    const changes: Record<string, unknown> = {};
    const then: Record<string, unknown> = {};
    if (f.route) then.route = f.route;
    if (f.suggest) then.suggest = Number(f.suggest);
    if (f.supplier) then.supplier = f.supplier;
    if (f.price) then.price = f.price;
    if (Object.keys(then).length) changes.then = then;
    if (f.enabled) changes.enabled = f.enabled === "yes";
    if (f.name) changes.name = f.name;
    return (
      <div className="space-y-3">
        <div><Label>Rule</Label><Select className="w-full" value={f.rule_id ?? ""} onChange={set("rule_id")}><option value="">Choose…</option>{body.rules.map((r) => <option key={r.id} value={r.id}>{r.id} {r.name} → {r.then.route}</option>)}</Select></div>
        {rule && (
          <div className="grid gap-3 sm:grid-cols-2">
            {field("route", `Route (now ${rule.then.route})`)}
            {rule.then.decision === "SOURCING_REQUEST" ? field("suggest", `Suggest N suppliers (now ${rule.then.suggest ?? 0})`, "", "number") : <>
              {field("supplier", `Supplier strategy (now ${rule.then.supplier})`, "preferred:1 / contract / fixed:S020")}
              {field("price", `Price strategy (now ${rule.then.price})`, "reference_price")}
            </>}
            {field("name", "New name (optional)")}
            <div><Label>Enabled</Label><Select className="w-full" value={f.enabled ?? ""} onChange={set("enabled")}><option value="">(unchanged)</option><option value="yes">yes</option><option value="no">no (disable)</option></Select></div>
          </div>
        )}
        <Button disabled={!rule || Object.keys(changes).length === 0} onClick={() => onAdd({ op: "modify_rule", rule_id: f.rule_id, changes })}><Plus className="h-4 w-4" /> Add change</Button>
      </div>
    );
  }
  if (type === "remove_rule") {
    return (
      <div className="space-y-3">
        <Select className="w-full" value={f.rule_id ?? ""} onChange={set("rule_id")}><option value="">Choose…</option>{body.rules.map((r) => <option key={r.id} value={r.id}>{r.id} {r.name}</option>)}</Select>
        <Button variant="destructive" disabled={!f.rule_id} onClick={() => onAdd({ op: "remove_rule", rule_id: f.rule_id })}>Remove rule</Button>
      </div>
    );
  }
  if (type === "add_item_set") {
    const list = (k: string) => (f[k] ?? "").split(",").map((s) => s.trim()).filter(Boolean);
    return (
      <div className="space-y-3">
        <div className="grid gap-3 sm:grid-cols-2">{field("name", "Set name (snake_case)", "oem_proprietary")}{field("label", "Label", "Proprietary OEM items")}</div>
        {field("codes", "Item codes (comma separated)", "ITM-1033, ITM-1034")}
        <div><Label>Categories (comma separated)</Label><Input list="cats" value={f.categories ?? ""} onChange={set("categories")} placeholder="Office & IT" /><datalist id="cats">{ctx.categories.map((c) => <option key={c} value={c} />)}</datalist></div>
        {field("patterns", "Description patterns (regex, comma separated)", "\\(vertex, \\(hydrax")}
        <Button disabled={!f.name || (!f.codes && !f.categories && !f.patterns)} onClick={() => onAdd({ op: "add_item_set", name: f.name, set: { label: f.label ?? "", codes: list("codes"), categories: list("categories"), patterns: list("patterns") } })}><Plus className="h-4 w-4" /> Add</Button>
        <p className="text-xs text-muted-foreground">Use it in a rule with the fact <code>item.in_set({f.name || "name"})</code>.</p>
      </div>
    );
  }
  if (type === "set_supplier_override") {
    return (
      <div className="space-y-3">
        <div><Label>Supplier</Label><Select className="w-full" value={f.supplier_id ?? ""} onChange={set("supplier_id")}><option value="">Choose…</option>{ctx.suppliers.map((s) => <option key={s.id} value={s.id}>{s.id} {s.name} ({s.status})</option>)}</Select></div>
        <div className="grid gap-3 sm:grid-cols-2">
          <div><Label>Treat as</Label><Select className="w-full" value={f.status ?? "Blocked"} onChange={set("status")}>{["Blocked", "Inactive", "Active"].map((s) => <option key={s}>{s}</option>)}</Select></div>
          {field("effective_from", "From date (optional)", "", "date")}
        </div>
        {field("reason", "Reason")}
        <Button disabled={!f.supplier_id} onClick={() => onAdd({ op: "set_supplier_override", supplier_id: f.supplier_id, status: f.status ?? "Blocked", reason: f.reason ?? "", ...(f.effective_from ? { effective_from: f.effective_from } : {}) })}><Plus className="h-4 w-4" /> Add</Button>
      </div>
    );
  }
  if (type === "set_ranking") {
    const w = body.preferred_suppliers.weights;
    const keys = ["frequency", "recency", "contract", "on_time", "quality"];
    const weights = Object.fromEntries(keys.map((k) => [k, f[k] !== undefined && f[k] !== "" ? Number(f[k]) : w[k]]));
    const total = keys.reduce((a, k) => a + Number(weights[k] ?? 0), 0);
    return (
      <div className="space-y-3">
        <div className="grid grid-cols-5 gap-2">{keys.map((k) => <div key={k}><Label>{k.replace("_", "-")}</Label><Input value={f[k] ?? String(w[k])} onChange={set(k)} /></div>)}</div>
        <div className={`text-xs ${Math.abs(total - 1) > 1e-9 ? "text-amber-700" : "text-muted-foreground"}`}>Sum of weights: {total.toFixed(2)}</div>
        <Button onClick={() => onAdd({ op: "set_ranking", changes: { weights } })}><Plus className="h-4 w-4" /> Add</Button>
      </div>
    );
  }
  if (type === "set_consolidation") {
    const poRoutes = [...new Set(body.rules.filter((r) => r.then.decision === "PO").map((r) => r.then.route))];
    const current = new Set((f.exclude ?? body.consolidation.exclude_routes.join(",")).split(",").filter(Boolean));
    return (
      <div className="space-y-2">
        <Label>Routes that are never consolidated into a multi-line PO</Label>
        {poRoutes.map((r) => (
          <label key={r} className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={current.has(r)} onChange={(e) => { const s = new Set(current); if (e.target.checked) s.add(r); else s.delete(r); setF({ exclude: [...s].join(",") }); }} /> {r}
          </label>
        ))}
        <Button onClick={() => onAdd({ op: "set_consolidation", changes: { exclude_routes: [...current] } })}><Plus className="h-4 w-4" /> Add</Button>
      </div>
    );
  }
  if (type === "set_clubbing") {
    return (
      <div className="space-y-3">
        <Select className="w-full" value={f.enabled ?? (body.clubbing.enabled ? "yes" : "no")} onChange={set("enabled")}><option value="yes">Clubbing on (policy 2.2)</option><option value="no">Clubbing off</option></Select>
        <p className="text-xs text-muted-foreground">The clubbing windows are parameters: change them with “Change a limit / window / number”.</p>
        <Button onClick={() => onAdd({ op: "set_clubbing", changes: { enabled: (f.enabled ?? (body.clubbing.enabled ? "yes" : "no")) === "yes" } })}><Plus className="h-4 w-4" /> Add</Button>
      </div>
    );
  }
  return null;
}

interface Cond { fact: string; op: string; mode: "value" | "param"; value: string }

function AddRuleForm({ ctx, ruleIds, routes, onAdd }: { ctx: Ctx; ruleIds: string[]; routes: string[]; onAdd: (op: Op) => void }) {
  const [meta, setMeta] = useState({ id: "R-NEW1", clause: "", name: "", posKind: "before", pos: ruleIds.find((r) => r.includes("5.3")) ?? ruleIds[0] });
  const [join, setJoin] = useState<"all" | "any">("all");
  const [conds, setConds] = useState<Cond[]>([{ fact: "req.plant", op: "eq", mode: "value", value: ctx.plants[0]?.code ?? "" }]);
  const [out, setOut] = useState({ decision: "PO", route: "", supplier: "preferred:1", price: "reference_price", suggest: "3", flags: "" });
  const factBy = useMemo(() => Object.fromEntries(ctx.facts.map((f) => [f.name.replace("(<set>)", ""), f])), [ctx.facts]);
  const params = Object.entries(ctx.body!.params);

  const coerce = (c: Cond): unknown => {
    const ft = factBy[c.fact.replace(/\(.*\)$/, "")]?.type;
    if (c.op === "in" || c.op === "not_in" || c.op === "between") return c.value.split(",").map((s) => s.trim()).filter(Boolean);
    if (ft === "bool") return c.value === "true";
    if (ft === "number" || ft === "money") return c.value;
    return c.value;
  };
  const leaves = conds.map((c) => (c.op === "exists" ? { fact: c.fact, op: c.op } : c.mode === "param" ? { fact: c.fact, op: c.op, param: c.value } : { fact: c.fact, op: c.op, value: coerce(c) }));
  const when = leaves.length === 1 ? leaves[0] : { [join]: leaves };
  const then: Record<string, unknown> = out.decision === "PO"
    ? { decision: "PO", route: out.route, supplier: out.supplier, price: out.price }
    : { decision: "SOURCING_REQUEST", route: out.route, suggest: Number(out.suggest) };
  if (out.flags.trim()) then.flags = out.flags.split(",").map((s) => s.trim()).filter(Boolean);
  const op: Op = { op: "add_rule", [meta.posKind]: meta.pos, rule: { id: meta.id, clause: meta.clause, name: meta.name || meta.id, when, then } };

  return (
    <div className="space-y-3 text-sm">
      <div className="grid gap-2 sm:grid-cols-3">
        <div><Label>Rule id</Label><Input value={meta.id} onChange={(e) => setMeta({ ...meta, id: e.target.value })} /></div>
        <div><Label>Clause</Label><Input value={meta.clause} onChange={(e) => setMeta({ ...meta, clause: e.target.value })} placeholder="5.3A" /></div>
        <div><Label>Name</Label><Input value={meta.name} onChange={(e) => setMeta({ ...meta, name: e.target.value })} placeholder="Emergency PO (Chakan)" /></div>
      </div>
      <div className="flex items-center gap-2">
        <Label className="mb-0">Evaluate</Label>
        <Select value={meta.posKind} onChange={(e) => setMeta({ ...meta, posKind: e.target.value })}><option value="before">before</option><option value="after">after</option></Select>
        <Select value={meta.pos} onChange={(e) => setMeta({ ...meta, pos: e.target.value })}>{ruleIds.map((r) => <option key={r}>{r}</option>)}</Select>
      </div>
      <div className="rounded-md border border-border p-2">
        <div className="mb-2 flex items-center gap-2 text-xs"><span className="font-medium">When</span>
          <Select className="h-7 text-xs" value={join} onChange={(e) => setJoin(e.target.value as "all" | "any")}><option value="all">all of</option><option value="any">any of</option></Select>
        </div>
        {conds.map((c, i) => {
          const base = c.fact.replace(/\(.*\)$/, "");
          const spec = factBy[base];
          const upd = (patch: Partial<Cond>) => setConds(conds.map((x, j) => (j === i ? { ...x, ...patch } : x)));
          return (
            <div key={i} className="mb-2 grid grid-cols-[1.3fr_0.7fr_0.6fr_1fr_auto] gap-1">
              <Select className="h-8 text-xs" value={base} onChange={(e) => upd({ fact: e.target.value === "item.in_set" ? `item.in_set(${Object.keys(ctx.body!.item_sets)[0] ?? "set"})` : e.target.value, op: factBy[e.target.value]?.ops[0] ?? "eq" })}>
                {ctx.facts.map((fct) => { const n = fct.name.replace("(<set>)", ""); return <option key={n} value={n}>{fct.label} ({n})</option>; })}
              </Select>
              <Select className="h-8 text-xs" value={c.op} onChange={(e) => upd({ op: e.target.value })}>{(spec?.ops ?? ["eq"]).map((o) => <option key={o}>{o}</option>)}</Select>
              <Select className="h-8 text-xs" value={c.mode} onChange={(e) => upd({ mode: e.target.value as "value" | "param", value: "" })} disabled={spec?.type === "bool"}>
                <option value="value">value</option><option value="param">param</option>
              </Select>
              {c.mode === "param" ? (
                <Select className="h-8 text-xs" value={c.value} onChange={(e) => upd({ value: e.target.value })}><option value="">param…</option>{params.map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}</Select>
              ) : spec?.type === "bool" ? (
                <Select className="h-8 text-xs" value={c.value || "true"} onChange={(e) => upd({ value: e.target.value })}><option value="true">true</option><option value="false">false</option></Select>
              ) : base === "req.plant" ? (
                <Select className="h-8 text-xs" value={c.value} onChange={(e) => upd({ value: e.target.value })}>{ctx.plants.map((p) => <option key={p.code} value={p.code}>{p.code} {p.name}</option>)}</Select>
              ) : base === "item.category" ? (
                <Select className="h-8 text-xs" value={c.value} onChange={(e) => upd({ value: e.target.value })}><option value="">category…</option>{ctx.categories.map((x) => <option key={x}>{x}</option>)}</Select>
              ) : base === "item.type" ? (
                <Select className="h-8 text-xs" value={c.value} onChange={(e) => upd({ value: e.target.value })}><option value="">type…</option>{ctx.types.map((x) => <option key={x}>{x}</option>)}</Select>
              ) : (
                <Input className="h-8 text-xs" value={c.value} onChange={(e) => upd({ value: e.target.value })} placeholder={c.op === "in" ? "a, b, c" : "value"} />
              )}
              <button onClick={() => setConds(conds.filter((_, j) => j !== i))} className="px-1 text-muted-foreground hover:text-red-600" aria-label="Remove condition"><Trash2 className="h-3.5 w-3.5" /></button>
            </div>
          );
        })}
        <Button size="sm" variant="ghost" onClick={() => setConds([...conds, { fact: "req.value", op: "lte", mode: "param", value: "" }])}><Plus className="h-3.5 w-3.5" /> condition</Button>
      </div>
      <div className="grid gap-2 sm:grid-cols-3">
        <div><Label>Outcome</Label><Select className="w-full" value={out.decision} onChange={(e) => setOut({ ...out, decision: e.target.value })}><option value="PO">PO</option><option value="SOURCING_REQUEST">Sourcing request</option></Select></div>
        <div><Label>Route (existing or new)</Label><Input list="routes" value={out.route} onChange={(e) => setOut({ ...out, route: e.target.value.toUpperCase().replace(/\s+/g, "_") })} placeholder="EMERGENCY_PO" /><datalist id="routes">{routes.map((r) => <option key={r} value={r} />)}</datalist></div>
        {out.decision === "PO" ? <>
          <div><Label>Supplier</Label><Select className="w-full" value={out.supplier} onChange={(e) => setOut({ ...out, supplier: e.target.value, price: e.target.value === "contract" ? "contract_rate" : out.price === "contract_rate" ? "reference_price" : out.price })}>
            <option value="preferred:1">1st preferred supplier</option><option value="contract">contract supplier</option>
            {ctx.suppliers.filter((s) => s.status === "Active").map((s) => <option key={s.id} value={`fixed:${s.id}`}>fixed: {s.id} {s.name}</option>)}
          </Select></div>
          <div><Label>Price</Label><Select className="w-full" value={out.price} onChange={(e) => setOut({ ...out, price: e.target.value })}>{["reference_price", "contract_rate", "last_po_price", "standard_price"].map((p) => <option key={p}>{p}</option>)}</Select></div>
        </> : <div><Label>Suggest N suppliers</Label><Input type="number" value={out.suggest} onChange={(e) => setOut({ ...out, suggest: e.target.value })} /></div>}
        <div><Label>Flags (optional)</Label><Input value={out.flags} onChange={(e) => setOut({ ...out, flags: e.target.value })} placeholder="CAPEX_APPROVAL" /></div>
      </div>
      <Button disabled={!out.route || !meta.id} onClick={() => onAdd(op)}><Plus className="h-4 w-4" /> Add rule</Button>
    </div>
  );
}
