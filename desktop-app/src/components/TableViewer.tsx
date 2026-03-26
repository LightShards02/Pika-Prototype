import { useMemo, useState } from 'react';
import { Search } from 'lucide-react';
import type { Appendix } from '../types';

export const TableViewer = ({ appendix }: { appendix: Appendix }) => {
  const [searchQuery, setSearchQuery] = useState('');
  const columns = appendix.columns ?? [];
  const rows = appendix.parsedRows ?? [];

  const filteredRows = useMemo(() => {
    if (!searchQuery) return rows;
    const query = searchQuery.toLowerCase();
    return rows.filter((row) =>
      columns.some((col) => (row[col] ?? '').toLowerCase().includes(query))
    );
  }, [rows, columns, searchQuery]);

  return (
    <div className="flex flex-col h-full bg-bg-panel border-r border-border-subtle overflow-hidden">
      <div className="p-4 border-b border-border-subtle bg-bg-primary">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-[13px] font-semibold text-text-primary truncate" title={appendix.fileName}>
            {appendix.fileName}
          </h2>
          <div className="flex items-center gap-2 shrink-0">
            <span className="px-2 py-0.5 bg-indigo-light text-indigo-mid text-[11px] font-bold rounded">
              {appendix.moduleTag}
            </span>
            <span className="px-1.5 py-0.5 bg-indigo-light text-indigo-mid text-[11px] font-bold rounded">
              {filteredRows.length}/{rows.length} ROWS
            </span>
          </div>
        </div>

        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-text-tertiary" size={16} />
          <input
            type="text"
            placeholder="Search rows..."
            className="w-full pl-10 pr-4 py-2 bg-bg-panel border border-border-medium rounded-md text-[13px] focus:outline-none focus:ring-1 focus:ring-accent-primary focus:border-accent-primary transition-all"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
        </div>
      </div>

      <div className="flex-1 overflow-auto">
        {columns.length === 0 ? (
          <div className="flex items-center justify-center h-full text-[13px] text-text-tertiary">
            No columns found
          </div>
        ) : (
          <table className="w-full border-collapse">
            <thead className="sticky top-0 z-10 bg-bg-elevated">
              <tr className="border-bottom border-border-subtle">
                {columns.map((col) => (
                  <th
                    key={col}
                    className="px-4 py-2.5 text-left text-[11px] font-semibold text-text-secondary uppercase tracking-wider whitespace-nowrap"
                  >
                    {col}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-border-subtle bg-bg-primary">
              {filteredRows.length === 0 ? (
                <tr>
                  <td colSpan={columns.length} className="px-4 py-8 text-center text-[13px] text-text-tertiary">
                    {rows.length === 0 ? 'No data' : 'No matching rows'}
                  </td>
                </tr>
              ) : (
                filteredRows.map((row, i) => (
                  <tr key={i} className="group h-10 hover:bg-bg-elevated transition-colors text-[13px]">
                    {columns.map((col) => (
                      <td key={col} className="px-4 py-2 text-text-secondary truncate max-w-xs">
                        {row[col] ?? ''}
                      </td>
                    ))}
                  </tr>
                ))
              )}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
};
