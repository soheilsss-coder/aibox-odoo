import React from "react";

// columns: [{ key, header, render? }]
// rows: array of plain objects; row.id used as React key when present.
export default function Table({ columns, rows, emptyText = "موردی یافت نشد." }) {
  if (!rows || rows.length === 0) {
    return <p className="muted">{emptyText}</p>;
  }
  return (
    <div className="ds-table-wrap">
      <table className="ds-table">
        <thead>
          <tr>
            {columns.map((col) => (
              <th key={col.key}>{col.header}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={row.id ?? i}>
              {columns.map((col) => (
                <td key={col.key}>{col.render ? col.render(row) : row[col.key]}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
