import React from "react";
import EmptyState from "./EmptyState.jsx";

// Config-driven table: columns: [{ key, header, render?(row), width? }]
// rows: array of objects. Shows a shared empty state when rows is empty.
export default function Table({ columns = [], rows = [], emptyText = "Nothing to show yet." }) {
  if (!rows.length) {
    return (
      <div className="table-wrap">
        <EmptyState icon="inbox" text={emptyText} />
      </div>
    );
  }
  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.key} style={c.width ? { width: c.width } : undefined}>{c.header}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={r.id ?? i}>
              {columns.map((c) => (
                <td key={c.key}>{c.render ? c.render(r) : r[c.key]}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
