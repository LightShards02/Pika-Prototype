import { ArrowLeft, X } from 'lucide-react';
import { useStore } from '../store';
import { clsx } from 'clsx';

export const TopBar = () => {
  const { run } = useStore();
  
  const getStatusColor = (status: string) => {
    switch (status) {
      case 'running': return 'bg-indigo-light text-indigo-mid';
      case 'paused': return 'bg-[#FFF3CD] text-[#856404]';
      case 'completed': return 'bg-[#DCFCE7] text-[#166534]';
      case 'failed': return 'bg-[#FEE2E2] text-[#991B1B]';
      default: return 'bg-bg-elevated text-text-tertiary';
    }
  };

  const getStatusLabel = (status: string) => {
    switch (status) {
      case 'running': return 'Running';
      case 'paused': return 'Paused at Gate';
      case 'completed': return 'Completed';
      case 'failed': return 'Failed';
      default: return 'Idle';
    }
  };

  return (
    <div className="h-16 border-b border-border-subtle bg-bg-primary flex items-center px-6 gap-6 shrink-0 z-10">
      <button className="p-2 hover:bg-bg-elevated rounded-full transition-colors cursor-pointer">
        <ArrowLeft size={20} className="text-text-secondary" />
      </button>
      
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-1">
          <h1 className="text-[15px] font-semibold text-text-primary">Design Improvement</h1>
          <div className={clsx(
            "px-2 py-0.5 rounded-full text-[11px] font-medium flex items-center gap-1.5",
            getStatusColor(run.status)
          )}>
            <div className={clsx(
              "w-1.5 h-1.5 rounded-full",
              run.status === 'running' ? "bg-accent-primary animate-pulse" : 
              run.status === 'paused' ? "bg-warning" : 
              run.status === 'completed' ? "bg-success" : 
              "bg-error"
            )} />
            {getStatusLabel(run.status)}
          </div>
        </div>
        <div className="text-[12px] text-text-tertiary flex items-center gap-2">
          <span>Run #{run.runId || '—'}</span>
          <span>·</span>
          <span className="truncate">{run.specPath || 'No spec loaded'}</span>
        </div>
      </div>

      <div className="flex-1 max-w-md">
        <div className="flex justify-between items-end mb-1.5 px-0.5">
          <span className="text-[11px] font-medium text-text-secondary">{run.progress}%</span>
        </div>
        <div className="h-1.5 bg-bg-elevated rounded-full overflow-hidden">
          <div 
            className="h-full bg-accent-primary transition-all duration-500 ease-out" 
            style={{ width: `${run.progress}%` }}
          />
        </div>
      </div>

      <button className="flex items-center gap-2 px-4 py-2 text-[13px] font-medium text-text-secondary border border-border-medium rounded-md hover:border-error hover:text-error transition-all cursor-pointer">
        <X size={16} />
        Cancel Run
      </button>
    </div>
  );
};
