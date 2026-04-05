import { useEffect, useRef, useState, useCallback } from 'react';
import { TopBar } from './components/TopBar';
import { LeftPanel } from './components/LeftPanel';
import { PipelineView } from './components/PipelineView';
import { GatePanel } from './components/GatePanel';
import { EntryScreen } from './components/EntryScreen';
import { SettingsPage } from './components/SettingsPage';
import { useStore, subscribeToPreferenceChanges } from './store';
import {
  parseStderrLine,
  mapStderrToPhaseUpdates,
  computeProgress,
  transformAgentItems,
} from './services/pikaService';
import { buildAppendixFromContent } from './services/appendixLoader';
import type { RawAgentItem, PikaPreferences } from './types';

function App() {
  const {
    run, setRun, updatePhase,
    setCurrentGateItems, setActiveItemIndex,
    designSpecPath, projectRootPath, configPath,
    view,
  } = useStore();

  // --- Preferences: load on mount, subscribe for auto-save ---
  useEffect(() => {
    let cancelled = false;

    const hydrate = async () => {
      try {
        const prefs = await window.electronAPI.loadPreferences();
        if (cancelled || !prefs) return;

        const validated = { ...prefs };

        if (validated.projectRootPath) {
          const exists = await window.electronAPI.pathExists(validated.projectRootPath);
          if (!exists) validated.projectRootPath = null;
        }
        if (validated.designSpecPath) {
          const exists = await window.electronAPI.pathExists(validated.designSpecPath);
          if (!exists) {
            validated.designSpecPath = null;
            validated.appendixRefs = [];
            validated.availableModuleTags = [];
          }
        }
        if (validated.configPath) {
          const exists = await window.electronAPI.pathExists(validated.configPath);
          if (!exists) validated.configPath = null;
        }

        const validRefs = [];
        for (const ref of validated.appendixRefs) {
          const exists = await window.electronAPI.pathExists(ref.filePath);
          if (exists) validRefs.push(ref);
        }
        validated.appendixRefs = validRefs;

        if (cancelled) return;
        useStore.getState().hydrateFromPreferences(validated as PikaPreferences);

        // Reload appendix content from disk
        for (const ref of validRefs) {
          if (cancelled) return;
          try {
            const content = await window.electronAPI.readFile(ref.filePath);
            const full = buildAppendixFromContent(ref, content);
            useStore.setState((state) => ({
              appendixes: state.appendixes.map((a) => a.id === ref.id ? full : a),
            }));
          } catch {
            useStore.setState((state) => ({
              appendixes: state.appendixes.filter((a) => a.id !== ref.id),
            }));
          }
        }
      } catch (err) {
        console.warn('Failed to load preferences:', err);
      }
    };

    hydrate();
    const unsubscribe = subscribeToPreferenceChanges();

    return () => {
      cancelled = true;
      unsubscribe();
    };
  }, []);

  const cleanupRef = useRef<(() => void) | null>(null);

  // Start refine process when run status transitions to 'running' and no process is active
  useEffect(() => {
    if (run.status !== 'running' || !projectRootPath) return;

    // Avoid re-triggering if we already have listeners (e.g. after gate resume)
    if (cleanupRef.current) return;

    const startRefine = async () => {
      // Accumulate ALL stderr lines for error diagnostics
      const stderrLines: string[] = [];

      // Register listeners BEFORE spawning the process to avoid race conditions
      // where a fast-exiting process sends events before listeners are ready.
      const unsubStderr = window.electronAPI.onPikaStderr((line: string) => {
        stderrLines.push(line);

        const event = parseStderrLine(line);
        if (!event) return;

        const command = useStore.getState().run.command;
        const updates = mapStderrToPhaseUpdates(event, command);
        for (const { phaseId, status } of updates) {
          updatePhase(phaseId, { status });
        }

        // Update progress based on current phase states
        const currentPhases = useStore.getState().phases;
        setRun({ progress: computeProgress(currentPhases, command) });
      });

      const unsubExit = window.electronAPI.onPikaExit(async (data) => {
        const { code, summary } = data;
        const status = summary?.status as string | undefined;

        if (status === 'completed') {
          // Safety net: mark phases done only if still pending/running
          const cmd = useStore.getState().run.command;
          const phaseIds = cmd === 'implement'
            ? ['I1', 'I5', 'I7', 'I14', 'B-EXEC']
            : ['R1', 'R2', 'R3', 'R4'];
          const currentPhases = useStore.getState().phases;
          for (const id of phaseIds) {
            const phase = currentPhases.find((p) => p.id === id);
            if (phase && (phase.status === 'pending' || phase.status === 'running')) {
              updatePhase(id, { status: 'done' });
            }
          }
          const updatedPhases = useStore.getState().phases;
          setRun({ status: 'completed', progress: computeProgress(updatedPhases, cmd) });
        } else if (status === 'blocked') {
          const runId = summary?.run_id as string | undefined;
          // Construct runDir from project root and run_id
          const runDir = runId
            ? `${projectRootPath}/out/agent_runs/refine/${runId}`
            : undefined;

          if (runDir) {
            try {
              const gateData = await window.electronAPI.readGateOutput({ runDir });
              const items = transformAgentItems(
                gateData.items as RawAgentItem[],
                useStore.getState().specs,
                gateData.format_version,
              );
              setCurrentGateItems(items);
              setActiveItemIndex(0);

              // Mark the blocked phase(s) based on blocking_stage from summary
              const blockingStage = summary?.blocking_stage as string | undefined;
              if (blockingStage === 'decomposition') {
                updatePhase('R2', { status: 'blocked' });
              } else if (blockingStage === 'agent_review') {
                updatePhase('R3', { status: 'blocked' });
                updatePhase('R4', { status: 'blocked' });
              }

              const pausedPhases = useStore.getState().phases;
              const cmd = useStore.getState().run.command;
              setRun({ status: 'paused', runDir, runId, progress: computeProgress(pausedPhases, cmd) });
            } catch {
              setRun({
                status: 'failed',
                errorDetails: { exitCode: code, stderr: stderrLines, summary },
              });
            }
          } else {
            setRun({
              status: 'failed',
              errorDetails: { exitCode: code, stderr: stderrLines, summary },
            });
          }
        } else {
          const failedPhases = useStore.getState().phases;
          const cmd = useStore.getState().run.command;
          setRun({
            status: 'failed',
            progress: computeProgress(failedPhases, cmd),
            errorDetails: { exitCode: code, stderr: stderrLines, summary },
          });
        }

        // Clean up listeners after exit
        cleanup();
      });

      const cleanup = () => {
        unsubStderr();
        unsubExit();
        cleanupRef.current = null;
      };

      cleanupRef.current = cleanup;

      // Now spawn the process — listeners are already registered
      try {
        await window.electronAPI.startRefine({
          projectRoot: projectRootPath,
          designSpecPath: designSpecPath ?? undefined,
          configPath: configPath ?? undefined,
        });
      } catch (err) {
        cleanup();
        setRun({
          status: 'failed',
          errorDetails: {
            exitCode: null,
            stderr: [`Failed to start process: ${err instanceof Error ? err.message : String(err)}`],
            summary: null,
          },
        });
      }
    };

    startRefine();

    return () => {
      if (cleanupRef.current) {
        cleanupRef.current();
      }
    };
  }, [run.status, projectRootPath]);

  // --- Resizable split panel ---
  const [leftWidthPercent, setLeftWidthPercent] = useState(45);
  const isDragging = useRef(false);
  const containerRef = useRef<HTMLElement | null>(null);

  const onMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    isDragging.current = true;
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
  }, []);

  useEffect(() => {
    const onMouseMove = (e: MouseEvent) => {
      if (!isDragging.current || !containerRef.current) return;
      const rect = containerRef.current.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const pct = (x / rect.width) * 100;
      // Clamp between 20% and 80%
      setLeftWidthPercent(Math.min(80, Math.max(20, pct)));
    };

    const onMouseUp = () => {
      if (!isDragging.current) return;
      isDragging.current = false;
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };

    window.addEventListener('mousemove', onMouseMove);
    window.addEventListener('mouseup', onMouseUp);
    return () => {
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('mouseup', onMouseUp);
    };
  }, []);

  if (view === 'settings') {
    return <SettingsPage />;
  }

  if (run.status === 'idle') {
    return <EntryScreen />;
  }

  return (
    <div className="flex flex-col h-screen bg-bg-primary select-none">
      <TopBar />

      <main ref={containerRef} className="flex flex-1 overflow-hidden">
        {/* Left Panel: Spec Viewer + Appendix Navigation */}
        <div className="flex-shrink-0 overflow-hidden" style={{ width: `${leftWidthPercent}%` }}>
          <LeftPanel />
        </div>

        {/* Drag handle */}
        <div
          onMouseDown={onMouseDown}
          className="w-1 flex-shrink-0 bg-border-primary hover:bg-accent-primary active:bg-accent-primary cursor-col-resize transition-colors duration-150"
        />

        {/* Right Panel: Pipeline or Gate */}
        <div className="flex-1 overflow-hidden relative">
          {run.status === 'paused' ? (
            <div className="absolute inset-0 z-20 animate-in fade-in slide-in-from-right-4 duration-300">
              <GatePanel />
            </div>
          ) : (
            <PipelineView />
          )}
        </div>
      </main>
    </div>
  );
}

export default App;
