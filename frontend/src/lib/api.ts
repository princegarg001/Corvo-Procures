/** Typed fetch wrapper: same-origin JSON/CSV, X-User from the role switcher, readable errors. */

export class ApiError extends Error {
  status: number;
  details: string[];
  constructor(status: number, message: string, details: string[] = []) {
    super(message);
    this.status = status;
    this.details = details;
  }
}

export function currentUser(): string {
  try {
    return localStorage.getItem("corvo.user") || "Rahul";
  } catch {
    return "Rahul";
  }
}

async function handle<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    let details: string[] = [];
    try {
      const body = await res.json();
      if (typeof body.detail === "string") msg = body.detail;
      else if (Array.isArray(body.detail)) msg = body.detail.map((d: { msg?: string }) => d.msg).join("; ");
      if (Array.isArray(body.errors)) details = body.errors;
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, msg, details);
  }
  const ctype = res.headers.get("content-type") || "";
  if (ctype.includes("application/json")) return (await res.json()) as T;
  return (await res.text()) as unknown as T;
}

function headers(extra: Record<string, string> = {}): Record<string, string> {
  return { "X-User": currentUser(), ...extra };
}

export const api = {
  get: <T>(url: string) => fetch(url, { headers: headers() }).then((r) => handle<T>(r)),
  post: <T>(url: string, body?: unknown) =>
    fetch(url, {
      method: "POST",
      headers: headers({ "Content-Type": "application/json" }),
      body: body === undefined ? undefined : JSON.stringify(body),
    }).then((r) => handle<T>(r)),
  put: <T>(url: string, body: unknown) =>
    fetch(url, {
      method: "PUT",
      headers: headers({ "Content-Type": "application/json" }),
      body: JSON.stringify(body),
    }).then((r) => handle<T>(r)),
  upload: <T>(url: string, file: File, fields: Record<string, string> = {}) => {
    const fd = new FormData();
    fd.append("file", file);
    Object.entries(fields).forEach(([k, v]) => fd.append(k, v));
    return fetch(url, { method: "POST", headers: headers(), body: fd }).then((r) => handle<T>(r));
  },
};

/** Download a URL as a file (CSV exports) with the user header. */
export async function download(url: string, fallbackName: string): Promise<void> {
  const res = await fetch(url, { headers: headers() });
  if (!res.ok) throw new ApiError(res.status, await res.text());
  const blob = await res.blob();
  const cd = res.headers.get("content-disposition") || "";
  const m = /filename="?([^"]+)"?/.exec(cd);
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = m ? m[1] : fallbackName;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

export function errorText(e: unknown): string {
  if (e instanceof ApiError) return e.details.length ? `${e.message}: ${e.details.join("; ")}` : e.message;
  if (e instanceof Error) return e.message;
  return String(e);
}
