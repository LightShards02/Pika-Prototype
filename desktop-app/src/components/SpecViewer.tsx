import { useMemo } from 'react';
import { Search, Filter, CheckCircle2 } from 'lucide-react';
import { useStore } from '../store';
import { clsx } from 'clsx';

export const SpecViewer = () => {
  const { specs, searchQuery, setSearchQuery, highlightedSpecIds } = useStore();

  const filteredSpecs = useMemo(() => {
    if (!searchQuery) return specs;
    const query = searchQuery.toLowerCase();
    return specs.filter(s => 
      s.spec_id.toLowerCase().includes(query) || 
      s.requirement.toLowerCase().includes(query) ||
      s.module_tag.toLowerCase().includes(query)
    );
  }, [specs, searchQuery]);

  return (
    <div className="flex flex-col h-full bg-bg-panel border-r border-border-subtle overflow-hidden">
      <div className="p-4 border-b border-border-subtle bg-bg-primary">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <h2 className="text-[13px] font-semibold text-indigo-dark uppercase tracking-wider">Design Spec</h2>
            <span className="px-1.5 py-0.5 bg-indigo-light text-indigo-mid text-[11px] font-bold rounded">
              {specs.length} SPECS
            </span>
          </div>
          <div className="flex gap-2">
            <button className="p-1.5 hover:bg-bg-elevated rounded transition-colors text-text-secondary cursor-pointer">
              <Filter size={16} />
            </button>
          </div>
        </div>
        
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-text-tertiary" size={16} />
          <input 
            type="text" 
            placeholder="Search specs..."
            className="w-full pl-10 pr-4 py-2 bg-bg-panel border border-border-medium rounded-md text-[13px] focus:outline-none focus:ring-1 focus:ring-accent-primary focus:border-accent-primary transition-all"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
        </div>
      </div>

      <div className="flex-1 overflow-auto">
        <table className="w-full border-collapse">
          <thead className="sticky top-0 z-10 bg-bg-elevated">
            <tr className="border-bottom border-border-subtle">
              <th className="px-4 py-2.5 text-left text-[11px] font-semibold text-text-secondary uppercase tracking-wider w-24">spec_id</th>
              <th className="px-4 py-2.5 text-left text-[11px] font-semibold text-text-secondary uppercase tracking-wider w-24">module</th>
              <th className="px-4 py-2.5 text-left text-[11px] font-semibold text-text-secondary uppercase tracking-wider">requirement</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border-subtle bg-bg-primary">
            {filteredSpecs.map((spec) => {
              const isHighlighted = highlightedSpecIds.includes(spec.spec_id);
              return (
                <tr 
                  key={spec.spec_id}
                  className={clsx(
                    "group h-10 hover:bg-bg-elevated transition-colors cursor-pointer text-[13px]",
                    isHighlighted ? "bg-bg-highlighted-row border-l-4 border-l-accent-primary" : "border-l-4 border-l-transparent"
                  )}
                >
                  <td className="px-4 py-2 font-mono text-indigo-mid font-semibold whitespace-nowrap">
                    <div className="flex items-center gap-2">
                      {spec.status === 'done' && <CheckCircle2 size={12} className="text-success" />}
                      {spec.spec_id}
                    </div>
                  </td>
                  <td className="px-4 py-2">
                    <span className="px-2 py-0.5 bg-indigo-light text-indigo-mid text-[11px] font-medium rounded-full">
                      {spec.module_tag}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-text-secondary truncate max-w-xs">
                    {spec.requirement}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
};
