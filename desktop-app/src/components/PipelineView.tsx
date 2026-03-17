import { CheckCircle2, AlertTriangle, XCircle, Circle, Loader2 } from 'lucide-react';
import { useStore } from '../store';
import { clsx } from 'clsx';
import type { PhaseStatus } from '../types';

const StatusIcon = ({ status }: { status: PhaseStatus }) => {
  switch (status) {
    case 'done': return <CheckCircle2 size={18} className="text-success" />;
    case 'failed': return <XCircle size={18} className="text-error" />;
    case 'blocked': return <AlertTriangle size={18} className="text-warning" />;
    case 'running': return <Loader2 size={18} className="text-accent-primary animate-spin" />;
    case 'waiting': return <Circle size={18} className="text-text-tertiary" />;
    default: return <div className="w-[18px] h-[18px] border-2 border-border-medium rounded-full" />;
  }
};

export const PipelineView = () => {
  const { phases, run } = useStore();

  const refinePhases = phases.filter(p => p.group === 'Refine');
  const implementPhases = phases.filter(p => p.group === 'Implement');
  const batchPhases = phases.filter(p => p.group === 'Batch');

  return (
    <div className="flex flex-col h-full bg-bg-primary overflow-y-auto p-8 gap-8">
      {/* Refine Section */}
      <section>
        <div className="flex items-center gap-3 mb-4">
          <div className="px-2 py-0.5 bg-indigo-dark text-white text-[10px] font-bold rounded uppercase tracking-widest">
            Refine
          </div>
          <div className="h-px flex-1 bg-border-subtle" />
        </div>
        
        <div className="space-y-1">
          {refinePhases.map((phase) => (
            <div 
              key={phase.id}
              className={clsx(
                "flex items-center p-3 rounded-lg transition-all border border-transparent",
                run.currentPhaseId === phase.id ? "bg-bg-elevated border-border-subtle shadow-sm" : "hover:bg-bg-panel"
              )}
            >
              <div className="w-8 flex justify-center">
                <StatusIcon status={phase.status} />
              </div>
              <div className="flex-1 ml-3">
                <div className="text-[14px] font-medium text-text-primary">{phase.name}</div>
                <div className="text-[12px] text-text-secondary truncate">{phase.description}</div>
              </div>
              <div className="text-[11px] font-semibold uppercase tracking-wider text-text-tertiary ml-4">
                {phase.status === 'done' ? '[DONE]' : 
                 phase.status === 'running' ? '[RUNNING]' : 
                 phase.status === 'blocked' ? '[BLOCKED]' : 
                 '[PENDING]'}
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* Implement Section */}
      <section>
        <div className="flex items-center gap-3 mb-4">
          <div className="px-2 py-0.5 bg-indigo-mid text-white text-[10px] font-bold rounded uppercase tracking-widest">
            Implement
          </div>
          <div className="h-px flex-1 bg-border-subtle" />
        </div>
        
        <div className="space-y-1">
          {implementPhases.map((phase) => (
            <div 
              key={phase.id}
              className={clsx(
                "flex items-center p-3 rounded-lg transition-all border border-transparent",
                run.currentPhaseId === phase.id ? "bg-bg-elevated border-border-subtle shadow-sm" : "hover:bg-bg-panel"
              )}
            >
              <div className="w-8 flex justify-center">
                <StatusIcon status={phase.status} />
              </div>
              <div className="flex-1 ml-3">
                <div className="text-[14px] font-medium text-text-primary">{phase.name}</div>
                <div className="text-[12px] text-text-secondary truncate">{phase.description}</div>
              </div>
              <div className="text-[11px] font-semibold uppercase tracking-wider text-text-tertiary ml-4">
                {phase.status === 'done' ? '[DONE]' : '[PENDING]'}
              </div>
            </div>
          ))}
        </div>
      </section>
      
      {/* Batch Execution (Simplified for Prototype) */}
      <section>
        <div className="flex items-center gap-3 mb-4">
          <div className="px-2 py-0.5 bg-indigo-light text-indigo-dark text-[10px] font-bold rounded uppercase tracking-widest">
            Batch Execution
          </div>
          <div className="h-px flex-1 bg-border-subtle" />
        </div>
        
        <div className="space-y-1">
          {batchPhases.map((phase) => (
            <div key={phase.id} className="flex items-center p-3 rounded-lg opacity-60">
              <div className="w-8 flex justify-center">
                <StatusIcon status={phase.status} />
              </div>
              <div className="flex-1 ml-3">
                <div className="text-[14px] font-medium text-text-primary">{phase.name}</div>
                <div className="text-[12px] text-text-secondary">Code generation and verification per batch.</div>
              </div>
              <div className="text-[11px] font-semibold uppercase tracking-wider text-text-tertiary ml-4">
                [PENDING]
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
};
