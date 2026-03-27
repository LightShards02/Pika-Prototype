import { useState } from 'react';
import { ArrowLeft, X, Settings, RotateCcw, FileWarning, Copy, Check } from 'lucide-react';
import { useStore } from '../store';
import { clsx } from 'clsx';

export const TopBar = () => {
  const { run, setRun, resetForNewRun, view, setView } = useStore();
  const [showErrorDetails, setShowErrorDetails] = useState(false);
  const [copied, setCopied] = useState(false);

  const isEntryScreen = run.status === 'idle' && view === 'main';

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

  const handleBack = async () => {
    if (view === 'settings') {
      setView('main');
      return;
    }
    if (run.status === 'running') {
      await window.electronAPI.cancelPika();
    }
    setRun({ status: 'idle', progress: 0, runId: undefined, runDir: undefined });
  };

  const handleCancel = async () => {
    await window.electronAPI.cancelPika();
    setRun({ status: 'failed' });
  };

  const handleRetry = () => {
    resetForNewRun();
    setRun({ status: 'idle', progress: 0, runId: undefined, runDir: undefined });
  };

  return (
    <div className="h-16 border-b border-border-subtle bg-bg-primary flex items-center px-6 gap-6 shrink-0 z-10">
      {!isEntryScreen && (
        <button
          onClick={handleBack}
          className="p-2 hover:bg-bg-elevated rounded-full transition-colors cursor-pointer"
        >
          <ArrowLeft size={20} className="text-text-secondary" />
        </button>
      )}

      <div className="flex-1 min-w-0">
        {isEntryScreen ? (
          <h1 className="text-[15px] font-semibold text-text-primary">PIKA</h1>
        ) : (
          <>
            <div className="flex items-center gap-2 mb-1">
              <h1 className="text-[15px] font-semibold text-text-primary">Design Improvement</h1>
              {run.status !== 'idle' && (
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
              )}
            </div>
            <div className="text-[12px] text-text-tertiary flex items-center gap-2">
              <span>Run #{run.runId || '—'}</span>
              <span>·</span>
              <span className="truncate">{run.specPath || 'No spec loaded'}</span>
            </div>
          </>
        )}
      </div>

      {run.status !== 'idle' && (
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
      )}

      {(run.status === 'running' || run.status === 'paused') && (
        <button
          onClick={handleCancel}
          className="flex items-center gap-2 px-4 py-2 text-[13px] font-medium text-text-secondary border border-border-medium rounded-md hover:border-error hover:text-error transition-all cursor-pointer"
        >
          <X size={16} />
          Cancel Run
        </button>
      )}

      {(run.status === 'failed' || run.status === 'completed') && (
        <div className="flex items-center gap-2">
          {run.status === 'failed' && run.errorDetails && (
            <button
              onClick={() => setShowErrorDetails(true)}
              className="flex items-center gap-2 px-4 py-2 text-[13px] font-medium text-text-secondary border border-border-medium rounded-md hover:border-error hover:text-error transition-all cursor-pointer"
            >
              <FileWarning size={16} />
              View Details
            </button>
          )}
          <button
            onClick={handleRetry}
            className="flex items-center gap-2 px-4 py-2 text-[13px] font-medium text-white bg-accent-primary rounded-md hover:bg-accent-deep transition-all cursor-pointer shadow-md"
          >
            <RotateCcw size={16} />
            {run.status === 'failed' ? 'Retry' : 'New Run'}
          </button>
        </div>
      )}

      {run.status === 'idle' && view === 'main' && (
        <button
          onClick={() => setView('settings')}
          className="p-2 hover:bg-bg-elevated rounded-full transition-colors cursor-pointer"
          title="Settings"
        >
          <Settings size={20} className="text-text-secondary" />
        </button>
      )}

      {/* Error Details Modal */}
      {showErrorDetails && run.errorDetails && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
          onClick={() => setShowErrorDetails(false)}
        >
          <div
            className="bg-white rounded-xl shadow-2xl border border-border-subtle w-[640px] max-h-[80vh] flex flex-col"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-6 py-4 border-b border-border-subtle">
              <div className="flex items-center gap-2">
                <FileWarning size={18} className="text-error" />
                <h2 className="text-[15px] font-semibold text-text-primary">Run Failed</h2>
              </div>
              <button
                onClick={() => setShowErrorDetails(false)}
                className="p-1.5 hover:bg-bg-elevated rounded-full transition-colors cursor-pointer"
              >
                <X size={16} className="text-text-tertiary" />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto p-6 space-y-4 select-text">
              {run.errorDetails.exitCode != null && (
                <div className="flex items-center gap-2 text-[13px]">
                  <span className="font-medium text-text-secondary">Exit code:</span>
                  <span className="font-mono text-error">{run.errorDetails.exitCode}</span>
                </div>
              )}

              {run.errorDetails.summary?.error && (
                <div className="p-3 bg-[#FEE2E2] border border-error/30 rounded-lg text-[13px] text-[#991B1B]">
                  {String(run.errorDetails.summary.error)}
                </div>
              )}

              {run.errorDetails.stderr.length > 0 && (
                <div>
                  <div className="text-[12px] font-semibold text-text-tertiary uppercase tracking-wider mb-2">
                    Process Output
                  </div>
                  <div className="relative group">
                    <button
                      onClick={() => {
                        navigator.clipboard.writeText(run.errorDetails!.stderr.join('\n'));
                        setCopied(true);
                        setTimeout(() => setCopied(false), 2000);
                      }}
                      className="absolute top-2 right-2 p-1.5 rounded-md bg-white/10 hover:bg-white/20 text-[#cdd6f4] transition-colors cursor-pointer opacity-0 group-hover:opacity-100"
                      title="Copy to clipboard"
                    >
                      {copied ? <Check size={14} /> : <Copy size={14} />}
                    </button>
                    <pre className="p-4 bg-[#1e1e2e] text-[#cdd6f4] text-[12px] font-mono rounded-lg overflow-x-auto max-h-[400px] overflow-y-auto leading-relaxed whitespace-pre-wrap break-words select-text">
                      {run.errorDetails.stderr.join('\n')}
                    </pre>
                  </div>
                </div>
              )}

              {run.errorDetails.stderr.length === 0 && !run.errorDetails.summary?.error && (
                <div className="text-[13px] text-text-tertiary italic">
                  No diagnostic output was captured. The process may have crashed before producing any output.
                </div>
              )}
            </div>

            <div className="px-6 py-4 border-t border-border-subtle flex justify-end">
              <button
                onClick={() => setShowErrorDetails(false)}
                className="px-4 py-2 text-[13px] font-medium text-text-secondary border border-border-medium rounded-md hover:bg-bg-elevated transition-colors cursor-pointer"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
