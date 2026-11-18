/** API shapes used by the UI (mirrors the FastAPI responses). */

export interface Meta {
  active_policy: string;
  effective_from: string;
  llm_available: boolean;
  today: string;
  timezone: string;
  database: string;
}

export interface User { id: number; name: string; role: "REQUESTER" | "BUYER" | "PROCUREMENT_ADMIN" }

export interface RunSummary {
  input_rows: number;
  requirements: number;
  purchase_orders: number;
  not_processed: number;
  routes_by_requirement: Record<string, number>;
  routes_by_line: Record<string, number>;
  flags: Record<string, number>;
  total_value: string;
  policy_versions_used: string[];
  refresh?: number;
}

export interface Run {
  id: number;
  name: string;
  kind: "BATCH" | "LIVE" | "IMPACT";
  input_file: string | null;
  input_hash: string;
  policy_pin: string | null;
  created_by: string;
  created_at: string;
  summary: RunSummary;
  duration_ms: number;
  approved_requirements?: number;
}

export type DecisionRow = Record<
  "pr_no" | "pr_line" | "resolved_item_code" | "group_id" | "po_id" | "decision" | "route" | "supplier_id" | "unit_price"
  | "group_value_inr" | "suggested_supplier_ids" | "policy_version" | "reason",
  string
>;

export interface ReqSummary {
  id: number;
  run_id: number;
  group_code: string;
  item_code: string;
  item_description: string;
  plant: string;
  req_date: string;
  created_at: string;
  emergency: boolean;
  value: string;
  status: "OPEN" | "APPROVED";
  policy_version: string;
  decision: string;
  route: string;
  supplier_id: string | null;
  supplier_name: string;
  unit_price: string | null;
  suggested: string[];
  rule_id: string | null;
  clause: string | null;
  contract_id: string | null;
  po_code: string | null;
  flags: string[];
  review_flags: string[];
  overridden: boolean;
  line_count: number;
  lines: { pr_no: string; line: number; requester: string; qty: string; uom: string }[];
}

export interface LadderStep {
  rule: string;
  clause: string;
  name: string;
  route: string;
  matched: boolean;
  fired: boolean;
  facts: Record<string, unknown>;
  params: Record<string, string>;
  note?: string;
}

export interface ContractOpt {
  id: string;
  supplier: string;
  rate: string;
  cap: string;
  consumed: string;
  remaining: string;
  required: string;
  usable: boolean;
  source: string;
}

export interface PreferredEntry {
  rank: number;
  supplier: string;
  score: string;
  components: Record<string, string>;
  po_count: number;
  last_po_date: string | null;
  contracts: string[];
  reference_price: string | null;
  reference_ref: string;
  explanation: string;
}

export interface Trace {
  requirement_id: string;
  policy_version: string;
  item_code: string;
  plant: string;
  requirement_date: string;
  lines: { pr_no: string; pr_line: number; created_at: string; qty: string; uom: string; need_by: string; urgency: string;
           description: string; requester: string; department: string;
           match: { method: string; score: string; candidates: [string, string][] } }[];
  value: { qty: string; price: string; source: string; ref: string; total: string };
  contracts: { applicable: ContractOpt[]; excluded: { id: string; why: string }[]; chosen: string | null };
  ladder: LadderStep[];
  outcome: { decision: string; route: string; rule: string | null; clause: string | null; supplier: string | null;
             unit_price: string | null; price_source: string; price_ref: string; contract: string | null;
             suggested: { supplier: string; source: string; why: string }[] };
  preferred: PreferredEntry[];
  flags: string[];
  po_id?: string;
  override?: { by: string; comment: string };
}

export interface ReqDetail extends Omit<ReqSummary, "lines"> {
  item: { code: string; description: string; uom: string; category: string; type: string; standard_price: string } | null;
  lines: Record<string, string | number | string[] | null>[];
  decision_id: number;
  reason: string;
  trace: Trace;
  history: { id: number; status: string; route: string; supplier_id: string | null; unit_price: string | null; value: string;
             reason: string; created_by: string; created_at: string; override_of: number | null }[];
  overrides: { id: number; route: string; supplier_id: string | null; price: string | null; comment: string; by: string; at: string }[];
  sourcing_events: { id: number; code: string; kind: string; suggested: string[]; status: string; created_by: string }[];
  audit: { actor: string; action: string; at: string; after: Record<string, unknown> | null }[];
  po: PO | null;
  eligible_suppliers: { id: string; name: string; categories: string[] }[];
  routes: { po: string[]; sourcing: string[] };
  supplier_names: Record<string, string>;
}

export interface PO {
  id: number;
  code: string;
  run_id: number;
  supplier_id: string;
  supplier_name: string;
  supplier_city: string;
  plant: string;
  plant_name: string;
  route: string;
  policy_version: string;
  status: "PROPOSED" | "APPROVED" | "ISSUED";
  created_at: string;
  issued_at: string | null;
  total: string;
  lines: { requirement_id: number; group_code: string; item_code: string; description: string; uom: string; qty: string;
           unit_price: string; amount: string; status: string; pr_lines: string[] }[];
}

export interface Inbox {
  run: Run | null;
  queues: {
    pos: { count: number; requirements: number; total: string;
           items: { po_code: string; po_id: number | null; supplier_id: string; supplier_name: string; plant: string; route: string;
                    requirements: ReqSummary[]; total: string; flags: string[] }[] };
    sourcing: { count: number; total: string; items: ReqSummary[] };
    review: { count: number; total: string; items: ReqSummary[] };
    done: { count: number; total: string; items: ReqSummary[] };
  };
}

export interface PolicyVersion {
  id: number;
  policy_id: string;
  version: string;
  effective_from: string;
  status: string;
  body_hash: string;
  created_by: string;
  created_at: string;
  approved_by: string | null;
  approved_at: string | null;
  body?: Record<string, unknown>;
  rules?: { id: string; clause: string; name: string; text: string; outcome: string; enabled: string }[];
  params?: { name: string; value: string; unit: string; label: string; clause: string }[];
  lint?: string[];
}

export interface Amendment {
  id: number;
  title: string;
  source_kind: "DOC" | "CHAT" | "EDITOR";
  source_text: string;
  source_filename: string | null;
  ops: Record<string, unknown>[];
  questions: string[];
  summary: { op: string; text: string; source_quote: string }[];
  impact: {
    available?: boolean;
    message?: string;
    run_id?: number;
    run_name?: string;
    requirements?: number;
    requirements_on_or_after_effective?: number;
    summary?: { lines_compared: number; lines_changed: number; route_moves: Record<string, number>; grouping_changes: number };
    changed?: { pr_no: string; pr_line: string; changes: Record<string, [string, string]>; new_reason: string; old_route: string; new_route: string }[];
    warnings?: string[];
  };
  lint: string[];
  errors: string[];
  ai_meta: Record<string, unknown>;
  status: "PROPOSED" | "INVALID" | "APPROVED" | "REJECTED";
  base_version: string | null;
  proposed_version: string | null;
  effective_from: string | null;
  created_by: string;
  created_at: string;
  decided_by: string | null;
  decided_at: string | null;
}

export interface FactInfo { name: string; type: string; label: string; description: string; ops: string[]; scope: string }

export interface Contract {
  id: string; supplier_id: string; supplier_name: string; supplier_status: string; start_date: string; end_date: string;
  value_cap: string; consumed_at_register: string; committed_live: string; consumed_live: string; remaining: string;
  source: "REGISTER" | "PDF"; plants: string[]; has_pdf: boolean; pdf_filename: string | null; validity: string;
  lines: { item_code: string; description: string; uom: string; rate: string }[];
}

export interface ChatMessage {
  id: number;
  role: "user" | "assistant";
  content: string;
  meta: {
    chips?: { label: string; value: string }[];
    card?: ConfirmCard;
    created?: { pr_no: string; run_id: number };
    value?: string;
  };
  at: string;
}

export interface ConfirmCard {
  lines: { item_code: string | null; description: string; qty: string; uom: string; is_new: boolean; est_price: string | null;
           preview: { route?: string; value?: string; group?: string; joins?: string[]; supplier_id?: string }; preview_text: string }[];
  plant: string;
  plant_name: string;
  need_by: string;
  need_by_label: string;
  urgency: string;
  requester: string;
}

export interface ChatSession {
  id: number;
  user: string;
  messages: ChatMessage[];
  state: { stage: string; pending: { type: string } | null; pr_no: string | null };
  draft: { lines: { item_code: string | null; description: string; qty: string | null; uom: string | null; is_new: boolean;
                    est_price: string | null; status: string }[];
           plant: string | null; need_by: string | null; urgency: string | null; stage: string; pr_no: string | null };
  new_message_ids?: number[];
}
