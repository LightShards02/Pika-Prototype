import { ChevronLeft, ChevronRight, CheckCircle2, Wand2, SkipForward, RefreshCcw, Loader2, Check, X, ArrowLeft } from 'lucide-react';
import { useStore } from '../store';
import { clsx } from 'clsx';
import { useEffect, useState } from 'react';
import type { ResolutionItem } from '../types';
import { computeProgress, getEnabledPhaseIds } from '../services/pikaService';

export const GatePanel = () => {
  const {
    currentGateItems,
    activeItemIndex,
    setActiveItemIndex,
    resolveItem,
    toggleAcceptConcern,
    setHighlightedSpecIds,
    setCurrentGateItems,
    run,
    setRun,
    setItemEditorOutput,
    setItemUserGuide,
    configPath,
    refineEnabled,
    implementEnabled,
    decompositionEnabled,
  } = useStore();

  const [isContinuing, setIsContinuing] = useState(false);

  // Agent-edit review sub-flow state
  const [agentEditPhase, setAgentEditPhase] = useState(false);
  const [agentEditQueue, setAgentEditQueue] = useState<ResolutionItem[]>([]);
  const [agentEditIndex, setAgentEditIndex] = useState(0);
  const [isInvokingAgent, setIsInvokingAgent] = useState(false);
  const [pendingPreview, setPendingPreview] = useState<Record<string, unknown> | null>(null);
  const [userGuideInput, setUserGuideInput] = useState('');
  const [agentError, setAgentError] = useState<string | null>(null);
  const [agentEditCompleted, setAgentEditCompleted] = useState(0);

  const currentItem = currentGateItems[activeItemIndex];
  const allResolved = currentGateItems.every(item => item.selectedOption);

  useEffect(() => {
    if (currentItem) {
      setHighlightedSpecIds(currentItem.spec_ids);
    }
  }, [currentItem, setHighlightedSpecIds]);


  if (!currentItem && !agentEditPhase) return null;

  const progress = Math.round(((currentGateItems.filter(i => i.selectedOption).length) / currentGateItems.length) * 100);

  // ── Proceed with write + apply + resume (shared final path) ──────────

  const proceedWithResolutions = async () => {
    if (!run.runDir || !run.runId || !run.projectRoot) return;
    setIsContinuing(true);

    try {
      // 1. Write resolutions to YAML (including editorOutput for agent-edit items)
      // Read fresh state to avoid stale closure after agent-edit accepts
      const freshItems = useStore.getState().currentGateItems;
      const resolutions = freshItems.map((item, idx) => ({
        itemIndex: item.itemIndex ?? idx,
        chosenOptionId: item.selectedOption!,
        editorOutput: item.editorOutput,
      }));
      await window.electronAPI.writeResolution({ runDir: run.runDir, resolutions });

      // 2. Apply resolutions (resolve --apply-only)
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

      // Mark gate-blocked phases done immediately — resolutions have been applied
      const phasesToClear = useStore.getState().phases.filter(p => p.status === 'blocked');
      for (const p of phasesToClear) {
        useStore.getState().updatePhase(p.id, { status: 'done' });
      }

      // 3. Resume the active command
      setCurrentGateItems([]);
      const resumePhases = useStore.getState().phases;
      setRun({ status: 'running', progress: computeProgress(resumePhases, getEnabledPhaseIds(refineEnabled, implementEnabled, decompositionEnabled)) });

      const resumeArgs = { projectRoot: run.projectRoot, runId: run.runId };
      if (run.command === 'implement') {
        await window.electronAPI.resumeImplement(resumeArgs);
      } else {
        await window.electronAPI.resumeRefine(resumeArgs);
      }

      const unsubResume = window.electronAPI.onPikaExit((data) => {
        unsubResume();
        const exitStatus = data.summary?.status as string | undefined;
        if (exitStatus === 'completed') {
          // Conditionally mark phases done (preserve failed/blocked state)
          const phases = useStore.getState().phases;
          const cmd = useStore.getState().run.command;
          const phaseIds = cmd === 'implement'
            ? ['I1', 'I5', 'I14', 'B-EXEC']
            : ['R1', 'R2', 'R3', 'R4'];
          for (const id of phaseIds) {
            const phase = phases.find((p) => p.id === id);
            if (phase && (phase.status === 'pending' || phase.status === 'running' || phase.status === 'blocked')) {
              useStore.getState().updatePhase(id, { status: 'done' });
            }
          }
          const updatedPhases = useStore.getState().phases;
          const { refineEnabled: re, implementEnabled: ie, decompositionEnabled: de } = useStore.getState();
          setRun({ status: 'completed', progress: computeProgress(updatedPhases, getEnabledPhaseIds(re, ie, de)) });
        } else {
          const failedPhases = useStore.getState().phases;
          const { refineEnabled: re2, implementEnabled: ie2, decompositionEnabled: de2 } = useStore.getState();
          setRun({ status: 'failed', progress: computeProgress(failedPhases, getEnabledPhaseIds(re2, ie2, de2)) });
        }
      });
    } catch {
      setRun({ status: 'failed' });
    } finally {
      setIsContinuing(false);
    }
  };

  // ── Handle Continue: check for pending agent edits first ─────────────

  const handleContinue = async () => {
    if (!run.runDir || !run.runId || !run.projectRoot) return;

    // Find items that selected "let_agent_edit" but don't have editorOutput yet
    const pendingAgentEdits = currentGateItems.filter(
      (item) => item.selectedOption === 'let_agent_edit' && !item.editorOutput
    );

    if (pendingAgentEdits.length > 0) {
      // Enter agent-edit review sub-flow
      setAgentEditPhase(true);
      setAgentEditQueue(pendingAgentEdits);
      setAgentEditIndex(0);
      setAgentEditCompleted(0);
      setUserGuideInput(pendingAgentEdits[0]?.userGuide ?? '');
      setPendingPreview(null);
      setAgentError(null);
      return;
    }

    // All agent edits already have results (or none selected) — proceed
    await proceedWithResolutions();
  };

  // ── Agent-edit handlers ──────────────────────────────────────────────

  const handleInvokeAgent = async () => {
    const item = agentEditQueue[agentEditIndex];
    if (!run.runId || !run.projectRoot) return;

    if (item.itemIndex === undefined || item.itemIndex === null) {
      setAgentError('Internal error: missing item index');
      return;
    }

    setIsInvokingAgent(true);
    setAgentError(null);
    setPendingPreview(null);

    try {
      const result = await window.electronAPI.invokeSpecEditor({
        projectRoot: run.projectRoot,
        runId: run.runId,
        itemIndex: item.itemIndex,
        userGuide: userGuideInput || undefined,
        configPath: configPath ?? undefined,
      });
      if (!result.editor_output) {
        setAgentError('Agent returned no edit proposal');
        return;
      }
      setPendingPreview(result.editor_output);
      // Always sync guidance to store (including empty, to clear stale values)
      setItemUserGuide(item.id, userGuideInput);
    } catch (err) {
      setAgentError(err instanceof Error ? err.message : 'Agent invocation failed');
    } finally {
      setIsInvokingAgent(false);
    }
  };

  const handleAcceptEdit = () => {
    const item = agentEditQueue[agentEditIndex];
    setItemEditorOutput(item.id, pendingPreview!);
    setPendingPreview(null);
    setAgentError(null);
    setAgentEditCompleted((c) => c + 1);

    if (agentEditIndex + 1 < agentEditQueue.length) {
      // Advance to next agent-edit item
      setAgentEditIndex(agentEditIndex + 1);
      setUserGuideInput(agentEditQueue[agentEditIndex + 1]?.userGuide ?? '');
    } else {
      // Stay on current item — user can review or click "Apply All"
    }
  };

  const handleRejectEdit = () => {
    setPendingPreview(null);
    setAgentError(null);
    // User stays on same item, can retry with different guidance
  };

  const handleExitAgentEdit = () => {
    // Go back to main gate view — user can change their selection
    setAgentEditPhase(false);
    setPendingPreview(null);
    setUserGuideInput('');
    setAgentError(null);
  };

  const handleSkipAgentEdit = () => {
    const item = agentEditQueue[agentEditIndex];
    resolveItem(item.id, 'skip');
    setPendingPreview(null);
    setAgentError(null);
    setAgentEditCompleted((c) => c + 1);

    if (agentEditIndex + 1 < agentEditQueue.length) {
      setAgentEditIndex(agentEditIndex + 1);
      setUserGuideInput(agentEditQueue[agentEditIndex + 1]?.userGuide ?? '');
    } else {
      // Stay on current item; user can use "Apply All" or navigate back
    }
  };

  const navigateAgentEdit = (newIndex: number) => {
    if (newIndex < 0 || newIndex >= agentEditQueue.length) return;
    setPendingPreview(null);
    setAgentError(null);
    setAgentEditIndex(newIndex);
    // Read fresh userGuide from store for the target item
    const targetId = agentEditQueue[newIndex].id;
    const storeItem = currentGateItems.find((i) => i.id === targetId);
    setUserGuideInput(storeItem?.userGuide ?? '');
  };

  const handleApplyAll = async () => {
    setIsContinuing(true);
    await proceedWithResolutions();
  };

  // ── Icon helper ──────────────────────────────────────────────────────

  const getOptionIcon = (optionId: string) => {
    switch (optionId) {
      case 'accept_suggestion':
      case 'accept_ambiguity':
      case 'accept_testability':
      case 'accept':
        return <CheckCircle2 size={20} />;
      case 'let_agent_edit':
      case 'agent':
        return <Wand2 size={20} />;
      case 'skip':
      default:
        return <SkipForward size={20} />;
    }
  };

  // ── Render: Agent-edit review sub-flow ───────────────────────────────

  if (agentEditPhase) {
    if (isContinuing) {
      return (
        <div className="flex flex-col items-center justify-center h-full bg-bg-gate-active gap-4">
          <Loader2 size={28} className="animate-spin text-accent-primary" />
          <span className="text-[14px] font-medium text-text-secondary">Applying resolutions...</span>
        </div>
      );
    }

    const editItem = agentEditQueue[agentEditIndex];
    // Check if current item already has an accepted edit in the store
    const storedOutput = currentGateItems.find((i) => i.id === editItem.id)?.editorOutput ?? null;
    // Check if all queue items are done (accepted or skipped)
    const allAgentEditsDone = agentEditQueue.every((qItem) => {
      const storeItem = currentGateItems.find((i) => i.id === qItem.id);
      return storeItem?.editorOutput || storeItem?.selectedOption === 'skip';
    });

    return (
      <div className="flex flex-col h-full bg-bg-gate-active overflow-hidden">
        {/* Header */}
        <div className="p-8 border-b border-border-subtle bg-white/50 backdrop-blur-sm">
          <div className="flex items-center gap-3 mb-2">
            <div className="p-1.5 bg-accent-primary/10 text-accent-primary rounded">
              <Wand2 size={20} />
            </div>
            <h2 className="text-[16px] font-semibold text-text-primary">Agent Edit Review</h2>
          </div>
          <p className="text-[14px] text-text-secondary mb-4">
            Review agent edits before applying. {agentEditCompleted} of {agentEditQueue.length} completed.
          </p>
          <div className="flex items-center gap-4">
            <div className="flex-1 h-2 bg-bg-elevated rounded-full overflow-hidden">
              <div
                className="h-full bg-accent-primary transition-all duration-300"
                style={{ width: `${Math.round((agentEditCompleted / agentEditQueue.length) * 100)}%` }}
              />
            </div>
            <button
              onClick={handleExitAgentEdit}
              className="flex items-center gap-2 px-4 py-2 rounded-md text-[13px] font-medium text-text-secondary hover:text-text-primary hover:bg-bg-elevated transition-all cursor-pointer"
            >
              <ArrowLeft size={16} />
              Back to Gate
            </button>
            {allAgentEditsDone && (
              <button
                onClick={handleApplyAll}
                className="flex items-center gap-2 px-5 py-2 rounded-md text-[13px] font-semibold bg-accent-primary text-white hover:bg-accent-deep shadow-md transition-all cursor-pointer"
              >
                <Check size={16} />
                Apply All
              </button>
            )}
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 p-8 overflow-y-auto">
          <div className="max-w-2xl mx-auto space-y-6">
            {/* Item context */}
            <div className="bg-white rounded-xl border border-border-subtle shadow-sm p-6 space-y-4">
              <div>
                <span className="px-2 py-0.5 bg-indigo-light text-indigo-dark text-[12px] font-mono font-semibold rounded">
                  {editItem.spec_ids.join(', ')}
                </span>
              </div>
              <div className="inline-block px-2 py-0.5 bg-error/10 text-error text-[11px] font-bold rounded uppercase">
                {editItem.type}
              </div>
              {editItem.currentText && (
                <div>
                  <div className="text-[12px] font-semibold text-text-tertiary uppercase mb-1">Current Text</div>
                  <div className="p-3 bg-bg-elevated rounded-lg font-mono text-[13px] text-text-primary leading-relaxed whitespace-pre-wrap break-words">
                    {editItem.currentText}
                  </div>
                </div>
              )}
              <p className="text-[14px] text-text-secondary leading-relaxed">
                <span className="font-semibold text-text-primary">Vague Phrases:</span> {editItem.reason}
              </p>
            </div>

            {/* State 1: Fresh pending preview (just returned from agent, not yet accepted) */}
            {pendingPreview && (
              <div className="bg-white rounded-xl border-2 border-accent-primary/30 shadow-sm p-6 space-y-5">
                <div className="text-[12px] font-semibold text-accent-primary uppercase">
                  Agent Proposal
                </div>

                {(pendingPreview.edit_type as string) === 'field' ? (
                  <div className="space-y-4">
                    <div>
                      <div className="text-[11px] font-bold text-text-tertiary uppercase mb-1">Field</div>
                      <span className="px-2 py-0.5 bg-bg-elevated text-text-secondary text-[12px] font-mono rounded">
                        {pendingPreview.field as string}
                      </span>
                    </div>
                    <div>
                      <div className="text-[11px] font-bold text-error/70 uppercase mb-1">Old</div>
                      <div className="p-3 bg-error/5 border border-error/15 rounded-lg font-mono text-[13px] text-text-primary leading-relaxed whitespace-pre-wrap break-words">
                        {editItem.currentText || '(empty)'}
                      </div>
                    </div>
                    <div>
                      <div className="text-[11px] font-bold text-green-700 uppercase mb-1">New</div>
                      <div className="p-3 bg-green-50 border border-green-200 rounded-lg font-mono text-[13px] text-text-primary leading-relaxed whitespace-pre-wrap break-words">
                        {pendingPreview.new_text as string}
                      </div>
                    </div>
                    {pendingPreview.rationale && (
                      <div>
                        <div className="text-[11px] font-bold text-text-tertiary uppercase mb-1">Rationale</div>
                        <p className="text-[13px] text-text-secondary italic">{pendingPreview.rationale as string}</p>
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="space-y-3">
                    {(pendingPreview.edits as Array<Record<string, unknown>>)?.map((edit, i) => (
                      <div key={i} className="flex items-start gap-3 p-3 bg-bg-elevated rounded-lg">
                        <span className={clsx(
                          "px-2 py-0.5 text-[11px] font-bold uppercase rounded",
                          (edit.action as string) === 'add' && "bg-green-100 text-green-700",
                          (edit.action as string) === 'update' && "bg-amber-100 text-amber-700",
                          (edit.action as string) === 'delete' && "bg-error/10 text-error",
                        )}>
                          {edit.action as string}
                        </span>
                        <div className="flex-1 min-w-0">
                          <span className="font-mono text-[12px] text-indigo-dark font-semibold">
                            {edit.spec_id as string}
                          </span>
                          {edit.row_data && (
                            <div className="mt-1 text-[12px] text-text-secondary whitespace-pre-wrap break-words">
                              {(edit.row_data as Record<string, string>).requirement}
                            </div>
                          )}
                        </div>
                      </div>
                    ))}
                    {pendingPreview.rationale && (
                      <div>
                        <div className="text-[11px] font-bold text-text-tertiary uppercase mb-1">Rationale</div>
                        <p className="text-[13px] text-text-secondary italic">{pendingPreview.rationale as string}</p>
                      </div>
                    )}
                  </div>
                )}

                <div className="flex gap-3 pt-2">
                  <button
                    onClick={handleAcceptEdit}
                    className="flex items-center gap-2 px-6 py-2.5 rounded-md text-[13px] font-semibold bg-green-600 text-white hover:bg-green-700 shadow-md transition-all cursor-pointer"
                  >
                    <Check size={16} />
                    Accept
                  </button>
                  <button
                    onClick={handleRejectEdit}
                    className="flex items-center gap-2 px-6 py-2.5 rounded-md text-[13px] font-semibold bg-white border-2 border-border-medium text-text-primary hover:border-error hover:text-error transition-all cursor-pointer"
                  >
                    <X size={16} />
                    Reject & Retry
                  </button>
                </div>
              </div>
            )}

            {/* State 2: Previously accepted edit (navigated back to a completed item) */}
            {!pendingPreview && storedOutput && (
              <div className="bg-white rounded-xl border-2 border-green-200 shadow-sm p-6 space-y-5">
                <div className="flex items-center gap-2">
                  <CheckCircle2 size={16} className="text-green-600" />
                  <span className="text-[12px] font-semibold text-green-700 uppercase">Accepted Edit</span>
                </div>

                {(storedOutput.edit_type as string) === 'field' ? (
                  <div className="space-y-4">
                    <div>
                      <div className="text-[11px] font-bold text-text-tertiary uppercase mb-1">Field</div>
                      <span className="px-2 py-0.5 bg-bg-elevated text-text-secondary text-[12px] font-mono rounded">
                        {storedOutput.field as string}
                      </span>
                    </div>
                    <div>
                      <div className="text-[11px] font-bold text-green-700 uppercase mb-1">Amended Text</div>
                      <div className="p-3 bg-green-50 border border-green-200 rounded-lg font-mono text-[13px] text-text-primary leading-relaxed whitespace-pre-wrap break-words">
                        {storedOutput.new_text as string}
                      </div>
                    </div>
                    {storedOutput.rationale && (
                      <div>
                        <div className="text-[11px] font-bold text-text-tertiary uppercase mb-1">Rationale</div>
                        <p className="text-[13px] text-text-secondary italic">{storedOutput.rationale as string}</p>
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="space-y-3">
                    {(storedOutput.edits as Array<Record<string, unknown>>)?.map((edit, i) => (
                      <div key={i} className="flex items-start gap-3 p-3 bg-bg-elevated rounded-lg">
                        <span className={clsx(
                          "px-2 py-0.5 text-[11px] font-bold uppercase rounded",
                          (edit.action as string) === 'add' && "bg-green-100 text-green-700",
                          (edit.action as string) === 'update' && "bg-amber-100 text-amber-700",
                          (edit.action as string) === 'delete' && "bg-error/10 text-error",
                        )}>
                          {edit.action as string}
                        </span>
                        <div className="flex-1 min-w-0">
                          <span className="font-mono text-[12px] text-indigo-dark font-semibold">
                            {edit.spec_id as string}
                          </span>
                          {edit.row_data && (
                            <div className="mt-1 text-[12px] text-text-secondary whitespace-pre-wrap break-words">
                              {(edit.row_data as Record<string, string>).requirement}
                            </div>
                          )}
                        </div>
                      </div>
                    ))}
                    {storedOutput.rationale && (
                      <div>
                        <div className="text-[11px] font-bold text-text-tertiary uppercase mb-1">Rationale</div>
                        <p className="text-[13px] text-text-secondary italic">{storedOutput.rationale as string}</p>
                      </div>
                    )}
                  </div>
                )}

                <button
                  onClick={() => {
                    setItemEditorOutput(editItem.id, undefined as unknown as Record<string, unknown>);
                    setAgentEditCompleted((c) => Math.max(0, c - 1));
                  }}
                  className="flex items-center gap-2 px-5 py-2.5 rounded-md text-[13px] font-medium text-text-secondary hover:text-text-primary hover:bg-bg-elevated border border-border-medium transition-all cursor-pointer"
                >
                  <RefreshCcw size={16} />
                  Re-run Agent
                </button>
              </div>
            )}

            {/* State 3: No preview, no stored output — show guidance form */}
            {!pendingPreview && !storedOutput && (
              <>
                <div className="bg-white rounded-xl border border-border-subtle shadow-sm p-6 space-y-4">
                  <div className="text-[12px] font-semibold text-text-tertiary uppercase">
                    Guidance for Agent (optional)
                  </div>
                  <textarea
                    value={userGuideInput}
                    onChange={(e) => setUserGuideInput(e.target.value.slice(0, 200))}
                    placeholder="e.g., Make the requirement measurable with a specific SLA..."
                    disabled={isInvokingAgent}
                    maxLength={200}
                    className="w-full p-3 rounded-lg border border-border-medium text-[14px] text-text-primary placeholder:text-text-tertiary resize-none focus:outline-none focus:border-accent-primary transition-colors"
                    rows={3}
                  />
                  <div className="text-[11px] text-text-tertiary text-right">
                    {userGuideInput.length}/200
                  </div>
                  <div className="flex gap-3">
                    <button
                      onClick={handleInvokeAgent}
                      disabled={isInvokingAgent}
                      className={clsx(
                        "flex items-center gap-2 px-6 py-2.5 rounded-md text-[13px] font-semibold transition-all cursor-pointer",
                        isInvokingAgent
                          ? "bg-border-medium text-text-tertiary cursor-not-allowed"
                          : "bg-accent-primary text-white hover:bg-accent-deep shadow-md"
                      )}
                    >
                      {isInvokingAgent ? (
                        <>
                          <Loader2 size={16} className="animate-spin" />
                          Running Agent...
                        </>
                      ) : (
                        <>
                          <Wand2 size={16} />
                          Run Agent
                        </>
                      )}
                    </button>
                    {!isInvokingAgent && (
                      <button
                        onClick={handleSkipAgentEdit}
                        className="flex items-center gap-2 px-4 py-2.5 rounded-md text-[13px] font-medium text-text-secondary hover:text-text-primary hover:bg-bg-elevated border border-border-medium transition-all cursor-pointer"
                      >
                        <SkipForward size={16} />
                        Skip Item
                      </button>
                    )}
                  </div>
                </div>

                {agentError && (
                  <div className="bg-error/5 border border-error/20 rounded-xl p-4">
                    <div className="text-[13px] font-semibold text-error mb-1">Agent Error</div>
                    <div className="text-[13px] text-error/80">{agentError}</div>
                    <button
                      onClick={() => setAgentError(null)}
                      className="mt-2 text-[12px] text-error underline cursor-pointer"
                    >
                      Dismiss and retry
                    </button>
                  </div>
                )}
              </>
            )}

            {/* Navigation */}
            <div className="flex justify-between items-center pt-4">
              <button
                disabled={agentEditIndex === 0 || isInvokingAgent}
                onClick={() => navigateAgentEdit(agentEditIndex - 1)}
                className="flex items-center gap-2 px-4 py-2 text-[14px] font-medium text-text-secondary hover:text-accent-primary disabled:opacity-30 cursor-pointer"
              >
                <ChevronLeft size={20} />
                Previous
              </button>
              <span className="text-[12px] font-medium text-text-tertiary">
                {agentEditIndex + 1} / {agentEditQueue.length}
              </span>
              <button
                disabled={agentEditIndex === agentEditQueue.length - 1 || isInvokingAgent}
                onClick={() => navigateAgentEdit(agentEditIndex + 1)}
                className="flex items-center gap-2 px-4 py-2 text-[14px] font-medium text-text-secondary hover:text-accent-primary disabled:opacity-30 cursor-pointer"
              >
                Next
                <ChevronRight size={20} />
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // ── Render: Main gate view (unchanged layout) ────────────────────────

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
          <div className="text-[12px] font-semibold text-text-tertiary uppercase tracking-wider">
            <span>ITEM {activeItemIndex + 1} OF {currentGateItems.length}</span>
          </div>

          <div className="bg-white rounded-xl border border-border-subtle shadow-sm p-6 space-y-6">
            {/* Spec badge + compound indicator */}
            <div>
              <div className="mb-3 flex items-center gap-2">
                <span className="px-2 py-0.5 bg-indigo-light text-indigo-dark text-[12px] font-mono font-semibold rounded">
                  {currentItem.spec_ids.join(', ')}
                </span>
                {currentItem.isCompound && (
                  <span className="px-2 py-0.5 bg-amber-100 text-amber-700 text-[11px] font-bold rounded">
                    {currentItem.concerns.length} issues
                  </span>
                )}
              </div>

              {/* --- Compound item: stacked concerns + shared actions --- */}
              {currentItem.isCompound ? (
                <div className="space-y-5">
                  {currentItem.concerns.map((concern) => {
                    const isAccepted = (currentItem.acceptedConcernIds ?? []).includes(concern.concernId);
                    const acceptOptionId = concern.agentType === 'ambiguity' ? 'accept_ambiguity' : 'accept_testability';
                    return (
                      <div key={concern.concernId} className="border border-border-subtle rounded-lg p-4 space-y-3">
                        <div className="flex items-center gap-2">
                          <span className={clsx(
                            "px-2 py-0.5 text-[11px] font-bold rounded uppercase",
                            concern.agentType === 'ambiguity'
                              ? "bg-purple-100 text-purple-700"
                              : "bg-orange-100 text-orange-700"
                          )}>
                            {concern.agentType}
                          </span>
                          <span className="text-[11px] font-mono text-text-tertiary">{concern.field}</span>
                        </div>
                        <h3 className="text-[16px] font-mono text-indigo-dark leading-relaxed">
                          &ldquo;{concern.currentText}&rdquo;
                        </h3>
                        <p className="text-[14px] text-text-secondary leading-relaxed">
                          <span className="font-semibold text-text-primary">
                            {concern.agentType === 'ambiguity' ? 'Vague Phrases:' : 'Untestable Reason:'}
                          </span>{' '}
                          {concern.reason}
                        </p>
                        {concern.suggestedText && (
                          <div className="space-y-2">
                            <div className="text-[12px] font-semibold text-text-tertiary uppercase">Suggested Rewrite</div>
                            <div className="p-3 bg-bg-highlighted-row rounded-lg font-mono text-[13px] text-indigo-mid border border-accent-light/30 leading-relaxed">
                              {concern.suggestedText}
                            </div>
                          </div>
                        )}
                        {/* Per-concern accept toggle */}
                        <button
                          onClick={() => toggleAcceptConcern(currentItem.id, concern.concernId)}
                          className={clsx(
                            "w-full flex items-center gap-3 p-3 rounded-lg border-2 text-left transition-all cursor-pointer",
                            isAccepted
                              ? "bg-green-600 border-transparent text-white shadow-md"
                              : "bg-white border-border-medium text-text-primary hover:border-green-500 hover:bg-green-50"
                          )}
                        >
                          <div className={clsx("p-1.5 rounded-md", isAccepted ? "bg-white/20" : "bg-bg-elevated")}>
                            <CheckCircle2 size={18} />
                          </div>
                          <div>
                            <div className="text-[13px] font-semibold">
                              {currentItem.options.find(o => o.id === acceptOptionId)?.label ?? 'Accept this fix'}
                            </div>
                          </div>
                        </button>
                      </div>
                    );
                  })}

                  {/* Shared actions: let_agent_edit and skip */}
                  <div className="grid grid-cols-1 gap-3 pt-2 border-t border-border-subtle">
                    {currentItem.options
                      .filter(o => o.id === 'let_agent_edit' || o.id === 'skip')
                      .map((option) => (
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
              ) : (
                /* --- Single item: original layout --- */
                <>
                  <div className="inline-block px-2 py-0.5 bg-error/10 text-error text-[11px] font-bold rounded uppercase mb-3">
                    {currentItem.type}
                  </div>
                  <h3 className="text-[18px] font-mono text-indigo-dark mb-4 leading-relaxed">
                    &ldquo;{currentItem.currentText}&rdquo;
                  </h3>
                  <p className="text-[14px] text-text-secondary leading-relaxed">
                    <span className="font-semibold text-text-primary">Vague Phrases:</span> {currentItem.reason}
                  </p>
                </>
              )}
            </div>

            {/* Suggested rewrite (single items only) */}
            {!currentItem.isCompound && currentItem.suggestedText && (
              <div className="space-y-3">
                <div className="text-[12px] font-semibold text-text-tertiary uppercase">Suggested Rewrite</div>
                <div className="p-4 bg-bg-highlighted-row rounded-lg font-mono text-[13px] text-indigo-mid border border-accent-light/30 leading-relaxed">
                  {currentItem.suggestedText}
                </div>
              </div>
            )}

            {/* Option buttons (single items only — compound uses inline buttons above) */}
            {!currentItem.isCompound && (
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
            )}
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
