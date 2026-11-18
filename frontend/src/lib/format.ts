/** en-IN formatting helpers: ₹1,37,531 · ₹2.3 L · Mon 16 Nov. The UI never computes decisions. */

const inr0 = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });
const inr2 = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export function toNum(v: string | number | null | undefined): number {
  if (v === null || v === undefined || v === "") return NaN;
  return typeof v === "number" ? v : Number(v);
}

/** ₹1,37,531 (whole rupees) or ₹7.06 when the value has paise and is small. */
export function inr(v: string | number | null | undefined, opts: { paise?: boolean } = {}): string {
  const n = toNum(v);
  if (Number.isNaN(n)) return "—";
  const paise = opts.paise ?? (Math.abs(n) < 1000 && Math.round(n) !== n);
  return "₹" + (paise ? inr2.format(n) : inr0.format(Math.round(n)));
}

/** Compact lakh / crore: ₹2.3 L, ₹1.2 Cr. */
export function inrShort(v: string | number | null | undefined): string {
  const n = toNum(v);
  if (Number.isNaN(n)) return "—";
  if (Math.abs(n) >= 1e7) return `₹${(n / 1e7).toFixed(2).replace(/\.?0+$/, "")} Cr`;
  if (Math.abs(n) >= 1e5) return `₹${(n / 1e5).toFixed(2).replace(/\.?0+$/, "")} L`;
  return inr(n);
}

export function qty(v: string | number | null | undefined): string {
  const n = toNum(v);
  return Number.isNaN(n) ? "—" : new Intl.NumberFormat("en-IN", { maximumFractionDigits: 3 }).format(n);
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

function parseDate(v: string): Date | null {
  if (!v) return null;
  const m = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?/.exec(v);
  if (!m) return null;
  return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]), Number(m[4] ?? 0), Number(m[5] ?? 0));
}

/** Mon 16 Nov (add the year when it is not 2026). */
export function day(v: string | null | undefined): string {
  const d = v ? parseDate(v) : null;
  if (!d) return "—";
  const yr = d.getFullYear() !== 2026 ? ` ${d.getFullYear()}` : "";
  return `${DAYS[d.getDay()]} ${d.getDate()} ${MONTHS[d.getMonth()]}${yr}`;
}

export function dayTime(v: string | null | undefined): string {
  const d = v ? parseDate(v) : null;
  if (!d) return "—";
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  return `${day(v)}, ${hh}:${mm}`;
}

export function ago(iso: string | null | undefined): string {
  if (!iso) return "";
  const t = new Date(iso).getTime();
  const s = Math.max(0, (Date.now() - t) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return `${Math.floor(s / 86400)} d ago`;
}

export function pct(v: number): string {
  return `${Math.round(v * 100)}%`;
}

export const ROUTE_TONE: Record<string, string> = {
  CONTRACT_PO: "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
  SPOT_PO: "bg-sky-50 text-sky-700 ring-sky-600/20",
  EMERGENCY_PO: "bg-rose-50 text-rose-700 ring-rose-600/20",
  RFQ: "bg-amber-50 text-amber-800 ring-amber-600/20",
  RFP: "bg-orange-50 text-orange-800 ring-orange-600/20",
  CAPEX_SOURCING: "bg-violet-50 text-violet-700 ring-violet-600/20",
  NEW_ITEM_SOURCING: "bg-fuchsia-50 text-fuchsia-700 ring-fuchsia-600/20",
  NOT_PROCESSED: "bg-zinc-100 text-zinc-600 ring-zinc-500/20",
  NEEDS_REVIEW: "bg-red-50 text-red-700 ring-red-600/20",
};

export function routeTone(route: string): string {
  return ROUTE_TONE[route] ?? "bg-indigo-50 text-indigo-700 ring-indigo-600/20";
}

export const FLAG_TEXT: Record<string, string> = {
  POSSIBLE_DUPLICATE: "Possible duplicate PR (same requester, minutes apart)",
  FUZZY_MATCH: "Item matched from free text — check the item",
  AMBIGUOUS_MATCH: "Several items matched equally",
  UOM_MISMATCH: "Unit differs from the item master",
  DESCRIPTION_MISMATCH: "Description does not look like the item code",
  ESTIMATE_REQUIRED: "New item without a price estimate",
  SHORT_LIST: "Fewer eligible suppliers than requested",
  NEED_BY_IN_PAST: "Need-by date is before the PR date",
  URGENT_IN_TEXT: "Text says 'urgent' but urgency is Normal",
  UNKNOWN_ITEM_CODE: "Item code given is not in the item master",
  CONTRACT_CEILING_EXHAUSTED: "Contract ceiling exhausted",
  VALUED_ON_NON_ACTIVE_SUPPLIER_PO: "Valued on a PO from a non-Active supplier (3.1b)",
  CAPEX_APPROVAL: "Needs capex approval",
  CLUBBED: "Several PR lines clubbed (policy 2.1)",
  NEW_ITEM: "New item",
  NO_RULE_MATCHED: "No rule matched — needs review",
  OVERRIDDEN: "Overridden by a buyer",
  REPEAT_IN_TEXT: "Marked as a repeat order",
  SAMPLE_REFERENCED: "Refers to a sample",
};
