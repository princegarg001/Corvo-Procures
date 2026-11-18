/** shadcn/ui-style primitives (Radix + cva + tailwind-merge), kept in one small module. */
import * as React from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
import { AlertTriangle, Inbox as InboxIcon, Loader2, X } from "lucide-react";
import { FLAG_TEXT, routeTone } from "@/lib/format";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium transition-colors " +
    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground shadow-sm hover:bg-primary/90",
        secondary: "bg-white text-foreground border border-border shadow-sm hover:bg-muted",
        ghost: "hover:bg-muted text-foreground",
        destructive: "bg-destructive text-white hover:bg-destructive/90",
        link: "text-primary underline-offset-4 hover:underline px-0",
        success: "bg-emerald-600 text-white shadow-sm hover:bg-emerald-600/90",
      },
      size: { default: "h-9 px-4", sm: "h-8 px-3 text-xs", lg: "h-11 px-6 text-base", icon: "h-9 w-9" },
    },
    defaultVariants: { variant: "default", size: "default" },
  },
);

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof buttonVariants> {
  asChild?: boolean;
  loading?: boolean;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild, loading, children, disabled, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp ref={ref} className={cn(buttonVariants({ variant, size }), className)} disabled={disabled || loading} {...props}>
        {loading && <Loader2 className="h-4 w-4 animate-spin" />}
        {children}
      </Comp>
    );
  },
);
Button.displayName = "Button";

export function Card({ className, ...p }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("rounded-lg border border-border bg-card shadow-sm", className)} {...p} />;
}
export function CardHeader({ className, ...p }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("flex items-start justify-between gap-3 border-b border-border px-4 py-3", className)} {...p} />;
}
export function CardTitle({ className, ...p }: React.HTMLAttributes<HTMLHeadingElement>) {
  return <h3 className={cn("text-sm font-semibold tracking-tight", className)} {...p} />;
}
export function CardBody({ className, ...p }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("p-4", className)} {...p} />;
}

export function Badge({ className, ...p }: React.HTMLAttributes<HTMLSpanElement>) {
  return (
    <span
      className={cn("inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-medium ring-1 ring-inset", className)}
      {...p}
    />
  );
}

export function RouteBadge({ route, className }: { route: string; className?: string }) {
  return <Badge className={cn(routeTone(route), className)}>{route.replace(/_/g, " ")}</Badge>;
}

export function FlagBadge({ flag }: { flag: string }) {
  const warn = !["CLUBBED", "NEW_ITEM", "OVERRIDDEN", "CAPEX_APPROVAL"].includes(flag);
  return (
    <Badge
      title={FLAG_TEXT[flag] ?? flag}
      className={warn ? "bg-amber-50 text-amber-800 ring-amber-600/25" : "bg-slate-50 text-slate-600 ring-slate-500/20"}
    >
      {warn && <AlertTriangle className="h-3 w-3" />}
      {FLAG_TEXT[flag] ? FLAG_TEXT[flag].split(" — ")[0] : flag.replace(/_/g, " ").toLowerCase()}
    </Badge>
  );
}

export function StatusBadge({ status }: { status: string }) {
  const tone: Record<string, string> = {
    ACTIVE: "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
    APPROVED: "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
    ISSUED: "bg-emerald-600 text-white ring-emerald-700",
    SUPERSEDED: "bg-slate-50 text-slate-600 ring-slate-500/20",
    PROPOSED: "bg-sky-50 text-sky-700 ring-sky-600/20",
    OPEN: "bg-sky-50 text-sky-700 ring-sky-600/20",
    DRAFT: "bg-slate-50 text-slate-600 ring-slate-500/20",
    INVALID: "bg-red-50 text-red-700 ring-red-600/20",
    REJECTED: "bg-zinc-100 text-zinc-500 ring-zinc-500/20",
    LAUNCHED: "bg-violet-50 text-violet-700 ring-violet-600/20",
    Valid: "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
    Expired: "bg-zinc-100 text-zinc-600 ring-zinc-500/20",
    "Not started": "bg-amber-50 text-amber-800 ring-amber-600/20",
    Active: "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
    Blocked: "bg-red-50 text-red-700 ring-red-600/20",
    Inactive: "bg-zinc-100 text-zinc-600 ring-zinc-500/20",
  };
  return <Badge className={tone[status] ?? "bg-slate-50 text-slate-600 ring-slate-500/20"}>{status}</Badge>;
}

export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  ({ className, ...p }, ref) => (
    <input
      ref={ref}
      className={cn(
        "h-9 w-full rounded-md border border-border bg-white px-3 text-sm shadow-sm placeholder:text-muted-foreground " +
          "focus:outline-none focus:ring-2 focus:ring-primary/30",
        className,
      )}
      {...p}
    />
  ),
);
Input.displayName = "Input";

export const Textarea = React.forwardRef<HTMLTextAreaElement, React.TextareaHTMLAttributes<HTMLTextAreaElement>>(
  ({ className, ...p }, ref) => (
    <textarea
      ref={ref}
      className={cn(
        "w-full rounded-md border border-border bg-white px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground " +
          "focus:outline-none focus:ring-2 focus:ring-primary/30",
        className,
      )}
      {...p}
    />
  ),
);
Textarea.displayName = "Textarea";

export function Select({ className, ...p }: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      className={cn(
        "h-9 rounded-md border border-border bg-white px-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-primary/30",
        className,
      )}
      {...p}
    />
  );
}

export function Label({ className, ...p }: React.LabelHTMLAttributes<HTMLLabelElement>) {
  return <label className={cn("mb-1 block text-xs font-medium text-muted-foreground", className)} {...p} />;
}

export function Spinner({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 p-6 text-sm text-muted-foreground">
      <Loader2 className="h-4 w-4 animate-spin" /> {label}
    </div>
  );
}

export function Empty({ title, children, icon }: { title: string; children?: React.ReactNode; icon?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-border p-10 text-center">
      <div className="text-muted-foreground">{icon ?? <InboxIcon className="h-8 w-8" />}</div>
      <div className="text-sm font-medium">{title}</div>
      {children && <div className="max-w-md text-sm text-muted-foreground">{children}</div>}
    </div>
  );
}

export function ErrorBox({ error, title = "Something went wrong" }: { error: unknown; title?: string }) {
  const msg = error instanceof Error ? error.message : String(error);
  const details = (error as { details?: string[] })?.details ?? [];
  return (
    <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800">
      <div className="font-medium">{title}</div>
      <div>{msg}</div>
      {details.length > 0 && (
        <ul className="mt-1 list-disc pl-5">
          {details.map((d) => (
            <li key={d}>{d}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function Notice({ tone = "info", children, className }: { tone?: "info" | "warn" | "ok"; children: React.ReactNode; className?: string }) {
  const t = {
    info: "border-sky-200 bg-sky-50 text-sky-900",
    warn: "border-amber-200 bg-amber-50 text-amber-900",
    ok: "border-emerald-200 bg-emerald-50 text-emerald-900",
  }[tone];
  return <div className={cn("rounded-md border p-3 text-sm", t, className)}>{children}</div>;
}

export function Bar({ value, max, tone = "bg-primary", className, label }: { value: number; max: number; tone?: string; className?: string; label?: string }) {
  const w = max > 0 ? Math.max(0, Math.min(100, (value / max) * 100)) : 0;
  return (
    <div className={cn("h-2 w-full overflow-hidden rounded-full bg-muted", className)} title={label}>
      <div className={cn("h-full rounded-full", tone)} style={{ width: `${w}%` }} />
    </div>
  );
}

export function Stat({ label, value, sub, onClick, active }: { label: string; value: React.ReactNode; sub?: React.ReactNode; onClick?: () => void; active?: boolean }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "rounded-lg border bg-white p-3 text-left shadow-sm transition-colors",
        onClick && "hover:border-primary/50",
        active ? "border-primary ring-2 ring-primary/20" : "border-border",
      )}
    >
      <div className="text-xs font-medium text-muted-foreground">{label}</div>
      <div className="num mt-1 text-xl font-semibold">{value}</div>
      {sub && <div className="num text-xs text-muted-foreground">{sub}</div>}
    </button>
  );
}

export function Tabs<T extends string>({ value, onChange, items }: { value: T; onChange: (v: T) => void; items: { value: T; label: React.ReactNode }[] }) {
  return (
    <div className="inline-flex rounded-md border border-border bg-muted p-0.5">
      {items.map((it) => (
        <button
          key={it.value}
          type="button"
          onClick={() => onChange(it.value)}
          className={cn(
            "rounded px-3 py-1.5 text-sm font-medium transition-colors",
            value === it.value ? "bg-white shadow-sm" : "text-muted-foreground hover:text-foreground",
          )}
        >
          {it.label}
        </button>
      ))}
    </div>
  );
}

export const Dialog = DialogPrimitive.Root;
export const DialogTrigger = DialogPrimitive.Trigger;
export function DialogContent({ title, description, children, className }: { title: string; description?: string; children: React.ReactNode; className?: string }) {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className="fixed inset-0 z-40 bg-black/30 backdrop-blur-[1px]" />
      <DialogPrimitive.Content
        className={cn(
          "fixed left-1/2 top-1/2 z-50 max-h-[90vh] w-[95vw] max-w-lg -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-lg border bg-white p-5 shadow-xl",
          className,
        )}
      >
        <div className="mb-3 flex items-start justify-between gap-4">
          <div>
            <DialogPrimitive.Title className="text-base font-semibold">{title}</DialogPrimitive.Title>
            {description && <DialogPrimitive.Description className="mt-1 text-sm text-muted-foreground">{description}</DialogPrimitive.Description>}
          </div>
          <DialogPrimitive.Close className="rounded p-1 text-muted-foreground hover:bg-muted" aria-label="Close">
            <X className="h-4 w-4" />
          </DialogPrimitive.Close>
        </div>
        {children}
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  );
}
export const DialogClose = DialogPrimitive.Close;

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: React.ReactNode; actions?: React.ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        {subtitle && <div className="mt-0.5 text-sm text-muted-foreground">{subtitle}</div>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Kbd({ children }: { children: React.ReactNode }) {
  return <kbd className="rounded border border-border bg-muted px-1.5 py-0.5 text-[11px] font-medium">{children}</kbd>;
}
