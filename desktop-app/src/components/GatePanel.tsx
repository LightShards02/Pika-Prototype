import { ChevronLeft, ChevronRight, CheckCircle2, Wand2, SkipForward, RefreshCcw } from 'lucide-react';
import { useStore } from '../store';
import { clsx } from 'clsx';
import { useEffect, useState } from 'react';

export const GatePanel = () => {
  const {
    currentGateItems,
    activeItemIndex,
    setActiveItemIndex,
    resolveItem,
    setHighlightedSpecIds,
    setCurrentGateItems,
    run,
    setRun,
  } = useStore();

  const [isContinuing, setIsContinuing] = useState(false);

  const currentItem = currentGateItems[activeItemIndex];
  const allResolved = currentGateItems.every(item => item.selectedOption);

  useEffect(() => {
    if (currentItem) {
      setHighlightedSpecIds(currentItem.spec_ids);
    }
  }, [currentItem, setHighlightedSpecIds]);

  if (!currentItem) return null;

  const progress = Math.round(((currentGateItems.filter(i => i.selectedOption).length) / currentGateItems.length) * 100);

  const handleContinue = async () => {
    if (!run.runDir || !run.runId || !run.projectRoot) return;
    setIsContinuing(true);

    try {
      // 1. Write resolutions to YAML
      const resolutions = currentGateItems.map((item, idx) => ({
        itemIndex: item.itemIndex ?? idx,
        chosenOptionId: item.selectedOption!,
      }));
      await window.electronAPI.writeResolution({ runDir: run.runDir, resolutions });

      // 2. Apply resolutions (resolve --apply-only)
      // Listen for the apply exit before resuming
      const waitForExit = () => new Promise<void>((resolve) => {
        const unsub = window.electronAPI.onPikaExit(() => {
          unsub();
          resolve();
        });
      });

      await window.electronAPI.applyResolutions({
        projectRoot: run.projectRoot,
        runId: run.runId,
      });
      await waitForExit();

      // 3. Resume refine
      setCurrentGateItems([]);
      setRun({ status: 'running', progress: 90 });

      await window.electronAPI.resumeRefine({
        projectRoot: run.projectRoot,
        runId: run.runId,
      });

      // The exit listener in App.tsx will handle the final status update
      // But we need a listener here for the resume exit
      const unsubResume = window.electronAPI.onPikaExit((data) => {
        unsubResume();
        const status = data.summary?.status as string | undefined;
        if (status === 'completed') {
          setRun({ status: 'completed', progress: 100 });
        } else {
          setRun({ status: 'failed' });
        }
      });
    } catch {
      setRun({ status: 'failed' });
    } finally {
      setIsContinuing(false);
    }
  };

  const getOptionIcon = (optionId: string) => {
    switch (optionId) {
      case 'accept_suggestion': return <CheckCircle2 size={20} />;
      case 'let_agent_edit': return <Wand2 size={20} />;
      case 'skip': return <SkipForward size={20} />;
      // Fallback for legacy mock option IDs
      case 'accept': return <CheckCircle2 size={20} />;
      case 'agent': return <Wand2 size={20} />;
      default: return <SkipForward size={20} />;
    }
  };

  return (
    <div className="flex flex-col h-full bg-bg-gate-active overflow-hidden">
      <div className="p-8 border-b border-border-subtle bg-white/50 backdrop-blur-sm">
        <div className="flex items-center gap-3 mb-2">
          <div className="p-1.5 bg-warning/10 text-warning rounded">
            <RefreshCcw size={20} />
          </div>
          <h2 className="text-[16px] font-semibold text-text-primary">Gate: Ambiguity & Testability Review</h2>
        </div>
        <p className="text-[14px] text-text-secondary mb-6">
          {currentGateItems.length} items need your review to continue.
        </p>

        <div className="flex items-center gap-4">
          <div className="flex-1 h-2 bg-bg-elevated rounded-full overflow-hidden">
            <div
              className="h-full bg-accent-primary transition-all duration-300"
              style={{ width: `${progress}%` }}
            />
          </div>
          <span className="text-[12px] font-medium text-text-secondary whitespace-nowrap">
            {currentGateItems.filter(i => i.selectedOption).length} / {currentGateItems.length} resolved
          </span>
          <button
            disabled={!allResolved || isContinuing}
            onClick={handleContinue}
            className={clsx(
              "px-6 py-2 rounded-md text-[13px] font-semibold transition-all cursor-pointer",
              allResolved && !isContinuing
                ? "bg-accent-primary text-white hover:bg-accent-deep shadow-md"
                : "bg-border-medium text-text-tertiary cursor-not-allowed"
            )}
          >
            {isContinuing ? 'Applying...' : 'Continue'}
          </button>
        </div>
      </div>

      <div className="flex-1 p-8 overflow-y-auto">
        <div className="max-w-2xl mx-auto space-y-6">
          <div className="flex items-center justify-between text-[12px] font-semibold text-text-tertiary uppercase tracking-wider">
            <span>ITEM {activeItemIndex + 1} OF {currentGateItems.length}</span>
            <span>{currentItem.spec_ids.join(', ')}</span>
          </div>

          <div className="bg-white rounded-xl border border-border-subtle shadow-sm p-6 space-y-6">
            <div>
              <div className="inline-block px-2 py-0.5 bg-error/10 text-error text-[11px] font-bold rounded uppercase mb-3">
                {currentItem.type}
              </div>
              <h3 className="text-[18px] font-mono text-indigo-dark mb-4 leading-relaxed">
                "{currentItem.currentText}"
              </h3>
              <p className="text-[14px] text-text-secondary leading-relaxed">
                <span className="font-semibold text-text-primary">Reason:</span> {currentItem.reason}
              </p>
            </div>

            {currentItem.suggestedText && (
              <div className="space-y-3">
                <div className="text-[12px] font-semibold text-text-tertiary uppercase">Suggested Rewrite</div>
                <div className="p-4 bg-bg-highlighted-row rounded-lg font-mono text-[13px] text-indigo-mid border border-accent-light/30 leading-relaxed">
                  {currentItem.suggestedText}
                </div>
              </div>
            )}

            <div className="grid grid-cols-1 gap-3">
              {currentItem.options.map((option) => (
                <button
                  key={option.id}
                  onClick={() => resolveItem(currentItem.id, option.id)}
                  className={clsx(
                    "w-full flex items-center gap-4 p-4 rounded-lg border-2 text-left transition-all cursor-pointer",
                    currentItem.selectedOption === option.id
                      ? "bg-accent-primary border-transparent text-white shadow-md"
                      : "bg-white border-border-medium text-text-primary hover:border-accent-primary hover:bg-bg-panel"
                  )}
                >
                  <div className={clsx(
                    "p-2 rounded-md",
                    currentItem.selectedOption === option.id ? "bg-white/20" : "bg-bg-elevated"
                  )}>
                    {getOptionIcon(option.id)}
                  </div>
                  <div>
                    <div className="text-[14px] font-semibold">{option.label}</div>
                    {option.description && (
                      <div className={clsx(
                        "text-[12px]",
                        currentItem.selectedOption === option.id ? "text-white/80" : "text-text-secondary"
                      )}>
                        {option.description}
                      </div>
                    )}
                  </div>
                </button>
              ))}
            </div>
          </div>

          <div className="flex justify-between items-center pt-4">
            <button
              disabled={activeItemIndex === 0}
              onClick={() => setActiveItemIndex(activeItemIndex - 1)}
              className="flex items-center gap-2 px-4 py-2 text-[14px] font-medium text-text-secondary hover:text-accent-primary disabled:opacity-30 cursor-pointer"
            >
              <ChevronLeft size={20} />
              Previous Item
            </button>
            <button
              disabled={activeItemIndex === currentGateItems.length - 1}
              onClick={() => setActiveItemIndex(activeItemIndex + 1)}
              className="flex items-center gap-2 px-4 py-2 text-[14px] font-medium text-text-secondary hover:text-accent-primary disabled:opacity-30 cursor-pointer"
            >
              Next Item
              <ChevronRight size={20} />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
