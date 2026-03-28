import { useMemo, useState, useRef, useEffect, useCallback } from 'react';
import { Search, Filter, CheckCircle2, ChevronDown, ChevronUp } from 'lucide-react';
import { useStore } from '../store';
import { clsx } from 'clsx';

export const SpecViewer = () => {
  const {
    specs, searchQuery, setSearchQuery, highlightedSpecIds,
    activeModuleFilters, setActiveModuleFilters,
    showHighlightedOnly, setShowHighlightedOnly,
  } = useStore();

  const [showFilters, setShowFilters] = useState(false);
  const [expandedSpecIds, setExpandedSpecIds] = useState<Set<string>>(new Set());
  const filterRef = useRef<HTMLDivElement>(null);

  const toggleExpand = useCallback((specId: string) => {
    setExpandedSpecIds(prev => {
      const next = new Set(prev);
      if (next.has(specId)) next.delete(specId);
      else next.add(specId);
      return next;
    });
  }, []);

  const hasActiveFilters = activeModuleFilters.length > 0 || showHighlightedOnly;

  // Close dropdown on outside click
  useEffect(() => {
    if (!showFilters) return;
    const handleClick = (e: MouseEvent) => {
      if (filterRef.current && !filterRef.current.contains(e.target as Node)) {
        setShowFilters(false);
      }
    };
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [showFilters]);

  const uniqueModuleTags = useMemo(() => {
    return [...new Set(specs.map(s => s.module_tag))].filter(Boolean).sort();
  }, [specs]);

  const filteredSpecs = useMemo(() => {
    let result = specs;

    if (activeModuleFilters.length > 0) {
      result = result.filter(s => activeModuleFilters.includes(s.module_tag));
    }

    if (showHighlightedOnly && highlightedSpecIds.length > 0) {
      result = result.filter(s => highlightedSpecIds.includes(s.spec_id));
    }

    if (searchQuery) {
      const query = searchQuery.toLowerCase();
      result = result.filter(s =>
        s.spec_id.toLowerCase().includes(query) ||
        s.requirement.toLowerCase().includes(query) ||
        s.module_tag.toLowerCase().includes(query)
      );
    }

    return result;
  }, [specs, searchQuery, activeModuleFilters, showHighlightedOnly, highlightedSpecIds]);

  const toggleModuleFilter = (tag: string) => {
    if (activeModuleFilters.includes(tag)) {
      setActiveModuleFilters(activeModuleFilters.filter(f => f !== tag));
    } else {
      setActiveModuleFilters([...activeModuleFilters, tag]);
    }
  };

  return (
    <div className="flex flex-col h-full bg-bg-panel border-r border-border-subtle overflow-hidden">
      <div className="p-4 border-b border-border-subtle bg-bg-primary">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <h2 className="text-[13px] font-semibold text-indigo-dark uppercase tracking-wider">Design Spec</h2>
            <span className="px-1.5 py-0.5 bg-indigo-light text-indigo-mid text-[11px] font-bold rounded">
              {filteredSpecs.length}/{specs.length} SPECS
            </span>
          </div>
          <div className="relative" ref={filterRef}>
            <button
              onClick={() => setShowFilters(!showFilters)}
              className={clsx(
                "p-1.5 hover:bg-bg-elevated rounded transition-colors cursor-pointer relative",
                hasActiveFilters ? "text-accent-primary" : "text-text-secondary"
              )}
            >
              <Filter size={16} />
              {hasActiveFilters && (
                <span className="absolute -top-0.5 -right-0.5 w-2 h-2 bg-accent-primary rounded-full" />
              )}
            </button>

            {showFilters && (
              <div className="absolute right-0 top-full mt-2 w-56 bg-white border border-border-medium rounded-lg shadow-lg z-30 p-3 space-y-3">
                <div className="text-[11px] font-semibold text-text-tertiary uppercase tracking-wider">
                  Filter by Module
                </div>
                <div className="max-h-40 overflow-y-auto space-y-1">
                  {uniqueModuleTags.map(tag => (
                    <label key={tag} className="flex items-center gap-2 px-2 py-1 rounded hover:bg-bg-elevated cursor-pointer">
                      <input
                        type="checkbox"
                        className="w-3.5 h-3.5 rounded"
                        checked={activeModuleFilters.includes(tag)}
                        onChange={() => toggleModuleFilter(tag)}
                      />
                      <span className="text-[12px] text-text-primary">{tag}</span>
                    </label>
                  ))}
                  {uniqueModuleTags.length === 0 && (
                    <div className="text-[12px] text-text-tertiary px-2 py-1">No modules loaded</div>
                  )}
                </div>

                {highlightedSpecIds.length > 0 && (
                  <>
                    <div className="h-px bg-border-subtle" />
                    <label className="flex items-center gap-2 px-2 py-1 rounded hover:bg-bg-elevated cursor-pointer">
                      <input
                        type="checkbox"
                        className="w-3.5 h-3.5 rounded"
                        checked={showHighlightedOnly}
                        onChange={(e) => setShowHighlightedOnly(e.target.checked)}
                      />
                      <span className="text-[12px] text-text-primary">Highlighted only</span>
                    </label>
                  </>
                )}

                {hasActiveFilters && (
                  <button
                    onClick={() => {
                      setActiveModuleFilters([]);
                      setShowHighlightedOnly(false);
                    }}
                    className="w-full text-[11px] text-accent-primary hover:text-accent-deep text-center py-1 cursor-pointer"
                  >
                    Clear all filters
                  </button>
                )}
              </div>
            )}
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
              const isExpanded = expandedSpecIds.has(spec.spec_id);
              return (
                <tr
                  key={spec.spec_id}
                  className={clsx(
                    "group hover:bg-bg-elevated transition-colors text-[13px]",
                    isHighlighted ? "bg-bg-highlighted-row border-l-4 border-l-accent-primary" : "border-l-4 border-l-transparent"
                  )}
                >
                  <td className={clsx(
                    "px-4 py-2 font-mono font-semibold whitespace-nowrap align-top",
                    isHighlighted ? "text-indigo-dark" : "text-indigo-mid"
                  )}>
                    <div className="flex items-center gap-2">
                      {spec.status === 'done' && <CheckCircle2 size={12} className="text-success" />}
                      {spec.spec_id}
                    </div>
                  </td>
                  <td className="px-4 py-2 align-top">
                    <span className="px-2 py-0.5 bg-indigo-light text-indigo-mid text-[11px] font-medium rounded-full">
                      {spec.module_tag}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-text-secondary">
                    <div className="flex items-start gap-2">
                      <div className="flex-1 min-w-0">
                        <div className={isExpanded ? "" : "truncate max-w-xs"}>
                          {spec.requirement}
                        </div>
                        {isExpanded && spec.acceptance_criteria && (
                          <div className="mt-2 pt-2 border-t border-border-subtle">
                            <div className="text-[11px] font-semibold text-text-tertiary uppercase tracking-wider mb-1">Acceptance Criteria</div>
                            <div className="text-[12px] text-text-secondary whitespace-pre-wrap">{spec.acceptance_criteria}</div>
                          </div>
                        )}
                      </div>
                      <button
                        onClick={() => toggleExpand(spec.spec_id)}
                        className="shrink-0 p-0.5 rounded hover:bg-bg-elevated text-text-tertiary hover:text-text-secondary transition-colors cursor-pointer"
                        title={isExpanded ? "Collapse" : "Expand"}
                      >
                        {isExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                      </button>
                    </div>
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
