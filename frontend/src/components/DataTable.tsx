import { useState } from "react";
import {
  flexRender, getCoreRowModel, getFilteredRowModel, getSortedRowModel, useReactTable,
  type ColumnDef, type SortingState,
} from "@tanstack/react-table";
import { ArrowDown, ArrowUp } from "lucide-react";
import { Input, cn } from "@/components/ui";

export function DataTable<T>({
  data, columns, search = true, placeholder = "Search…", onRowClick, rowClassName, initialSort, maxHeight = "70vh", toolbar,
}: {
  data: T[];
  columns: ColumnDef<T, unknown>[];
  search?: boolean;
  placeholder?: string;
  onRowClick?: (row: T) => void;
  rowClassName?: (row: T) => string;
  initialSort?: SortingState;
  maxHeight?: string;
  toolbar?: React.ReactNode;
}) {
  const [sorting, setSorting] = useState<SortingState>(initialSort ?? []);
  const [filter, setFilter] = useState("");
  const table = useReactTable({
    data,
    columns,
    state: { sorting, globalFilter: filter },
    onSortingChange: setSorting,
    onGlobalFilterChange: setFilter,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    globalFilterFn: "includesString",
  });
  const rows = table.getRowModel().rows;
  return (
    <div className="space-y-2">
      {(search || toolbar) && (
        <div className="flex flex-wrap items-center gap-2">
          {search && <Input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder={placeholder} className="h-8 max-w-xs" />}
          {toolbar}
          <span className="ml-auto text-xs text-muted-foreground">{rows.length} of {data.length} rows</span>
        </div>
      )}
      <div className="overflow-auto rounded-lg border border-border bg-white scrollbar-thin" style={{ maxHeight }}>
        <table className="w-full border-collapse text-sm">
          <thead className="sticky top-0 z-10 bg-muted/90 backdrop-blur">
            {table.getHeaderGroups().map((hg) => (
              <tr key={hg.id}>
                {hg.headers.map((h) => (
                  <th
                    key={h.id}
                    onClick={h.column.getCanSort() ? h.column.getToggleSortingHandler() : undefined}
                    className={cn(
                      "whitespace-nowrap border-b border-border px-3 py-2 text-left text-xs font-semibold text-muted-foreground",
                      h.column.getCanSort() && "cursor-pointer select-none hover:text-foreground",
                    )}
                  >
                    <span className="inline-flex items-center gap-1">
                      {flexRender(h.column.columnDef.header, h.getContext())}
                      {h.column.getIsSorted() === "asc" && <ArrowUp className="h-3 w-3" />}
                      {h.column.getIsSorted() === "desc" && <ArrowDown className="h-3 w-3" />}
                    </span>
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr
                key={r.id}
                onClick={onRowClick ? () => onRowClick(r.original) : undefined}
                className={cn("border-b border-border/70 last:border-0", onRowClick && "cursor-pointer hover:bg-accent", rowClassName?.(r.original))}
              >
                {r.getVisibleCells().map((c) => (
                  <td key={c.id} className="px-3 py-2 align-top">
                    {flexRender(c.column.columnDef.cell, c.getContext())}
                  </td>
                ))}
              </tr>
            ))}
            {rows.length === 0 && (
              <tr>
                <td colSpan={columns.length} className="p-6 text-center text-sm text-muted-foreground">No rows match.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
