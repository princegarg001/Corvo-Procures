import { Component, type ErrorInfo, type ReactNode } from "react";

/** Shows the real error (and a reload button) instead of a blank white page. */
export class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) {
    return { error };
  }
  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("UI crash:", error, info.componentStack);
  }
  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="mx-auto mt-16 max-w-xl rounded-lg border border-red-200 bg-red-50 p-6 text-sm text-red-900">
        <div className="text-base font-semibold">This page hit an error</div>
        <p className="mt-1">Reloading usually fixes it. If it keeps happening, send this message to the developer:</p>
        <pre className="mt-3 whitespace-pre-wrap break-words rounded bg-white p-3 text-xs">{String(this.state.error.stack || this.state.error.message).slice(0, 900)}</pre>
        <button className="mt-4 rounded-md bg-red-700 px-4 py-2 font-medium text-white" onClick={() => location.reload()}>
          Reload
        </button>
      </div>
    );
  }
}
