import { useState, useEffect, useRef } from 'react';
import { useStore } from '../store';
import { PipelineView } from './PipelineView';
import { GatePanel } from './GatePanel';

export const RightPanel = () => {
  const { run, currentGateItems } = useStore();
  const [activeTab, setActiveTab] = useState<'phases' | 'gate'>('phases');
  const prevStatus = useRef(run.status);

  // Auto-switch: paused → gate tab; returning from paused → phases tab
  useEffect(() => {
    if (run.status === 'paused') {
      setActiveTab('gate');
    } else if (prevStatus.current === 'paused') {
      setActiveTab('phases');
    }
    prevStatus.current = run.status;
  }, [run.status]);

  const unresolvedCount = currentGateItems.filter(i => !i.selectedOption).length;

  return (
    <div className="flex flex-col h-full bg-bg-primary">
      {/* Nav bar */}
      <div className="flex flex-shrink-0 border-b border-border-subtle bg-bg-panel">
        {(['phases', 'gate'] as const).map((tab, i) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={[
              'flex-1 flex items-center justify-center gap-2 py-3 text-[13px] font-semibold transition-colors select-none',
              i === 0 ? 'border-r border-border-subtle' : '',
              activeTab === tab
                ? 'text-accent-primary border-b-2 border-accent-primary -mb-px bg-bg-primary'
                : 'text-text-secondary hover:text-text-primary hover:bg-bg-elevated',
            ].join(' ')}
          >
            {tab === 'phases' ? 'Phase Status' : 'Gate View'}
            {tab === 'gate' && run.status === 'paused' && unresolvedCount > 0 && (
              <span className="px-1.5 py-0.5 bg-warning/20 text-warning text-[10px] font-bold rounded-full leading-none">
                {unresolvedCount}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-hidden">
        {activeTab === 'phases' ? (
          <PipelineView />
        ) : run.status === 'paused' ? (
          <GatePanel />
        ) : (
          <div className="flex flex-col items-center justify-center h-full gap-3 text-text-tertiary">
            <div className="w-10 h-10 rounded-full border-2 border-border-medium flex items-center justify-center">
              <svg width="20" height="20" viewBox="0 0 20 20" fill="none" className="text-border-medium">
                <path d="M4 10l4 4 8-8" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </div>
            <p className="text-[14px] font-medium text-text-secondary">Run is still processing</p>
            <p className="text-[12px]">Nothing is currently blocked</p>
          </div>
        )}
      </div>
    </div>
  );
};
