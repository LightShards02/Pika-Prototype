import { useEffect, useRef, useState, useCallback } from 'react';
import { TopBar } from './components/TopBar';
import { LeftPanel } from './components/LeftPanel';
import { RightPanel } from './components/RightPanel';
import { EntryScreen } from './components/EntryScreen';
import { SettingsPage } from './components/SettingsPage';
import { useStore, subscribeToPreferenceChanges } from './store';
import {
  parseStderrLine,
  mapStderrToPhaseUpdates,
  computeProgress,
  getEnabledPhaseIds,
  transformAgentItems,
  transformImplementItems,
} from './services/pikaService';
import { buildAppendixFromContent } from './services/appendixLoader';
import type { RawAgentItem, RawImplementItem, PikaPreferences } from './types';

function App() {
  const {
    run, setRun, updatePhase,
    setCurrentGateItems, setActiveItemIndex,
    designSpecPath, projectRootPath, configPath,
    view, refineEnabled, implementEnabled, decompositionEnabled,
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

  // Start refine/implement process when run status transitions to 'running' and no process is active
  useEffect(() => {
    if (run.status !== 'running' || !projectRootPath) return;

    // Avoid re-triggering if we already have listeners
    if (cleanupRef.current) return;

    // If runId is set this is a gate resume — GatePanel owns the spawn, don't double-start
    if (useStore.getState().run.runId) return;

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

        // Update progress based on current phase states across whole pipeline
        const currentPhases = useStore.getState().phases;
        const { refineEnabled: re, implementEnabled: ie, decompositionEnabled: de } = useStore.getState();
        setRun({ progress: computeProgress(currentPhases, getEnabledPhaseIds(re, ie, de)) });
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
          const { refineEnabled: re2, implementEnabled: ie2, decompositionEnabled: de2 } = useStore.getState();
          setRun({ status: 'completed', progress: computeProgress(updatedPhases, getEnabledPhaseIds(re2, ie2, de2)) });
        } else if (status === 'blocked') {
          const runId = summary?.run_id as string | undefined;
          // Construct runDir from project root, active command, and run_id
          const activeCmd = useStore.getState().run.command ?? 'refine';
          const runDir = runId
            ? `${projectRootPath}/out/agent_runs/${activeCmd}/${runId}`
            : undefined;

          if (runDir) {
            // Mark the blocked phase(s) immediately — before the async read so it always happens
            const blockingStage = summary?.blocking_stage as string | undefined;
            if (activeCmd === 'implement') {
              updatePhase('I7', { status: 'blocked' });
            } else if (blockingStage === 'decomposition') {
              updatePhase('R2', { status: 'blocked' });
            } else {
              // agent_review (or unknown refine stage) — mark R3 + R4
              updatePhase('R3', { status: 'blocked' });
              updatePhase('R4', { status: 'blocked' });
            }

            try {
              const gateData = await window.electronAPI.readGateOutput({ runDir });
              const items = activeCmd === 'implement'
                ? transformImplementItems(gateData.items as RawImplementItem[])
                : transformAgentItems(gateData.items as RawAgentItem[], useStore.getState().specs);
              setCurrentGateItems(items);
              setActiveItemIndex(0);

              const pausedPhases = useStore.getState().phases;
              const { refineEnabled: re3, implementEnabled: ie3, decompositionEnabled: de3 } = useStore.getState();
              setRun({ status: 'paused', runDir, runId, progress: computeProgress(pausedPhases, getEnabledPhaseIds(re3, ie3, de3)) });
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
          const { refineEnabled: re4, implementEnabled: ie4, decompositionEnabled: de4 } = useStore.getState();
          setRun({
            status: 'failed',
            progress: computeProgress(failedPhases, getEnabledPhaseIds(re4, ie4, de4)),
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
        const cmd = useStore.getState().run.command;

        // Mark the first phase of the command as running so the UI shows activity immediately
        updatePhase(cmd === 'implement' ? 'I1' : 'R1', { status: 'running' });
        if (cmd === 'implement') {
          await window.electronAPI.startImplement({
            projectRoot: projectRootPath,
            designSpecPath: designSpecPath ?? undefined,
            configPath: configPath ?? undefined,
          });
        } else {
          await window.electronAPI.startRefine({
            projectRoot: projectRootPath,
            designSpecPath: designSpecPath ?? undefined,
            configPath: configPath ?? undefined,
          });
        }
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

  // Auto-advance: when a command completes, start the next enabled command
  useEffect(() => {
    if (run.status !== 'completed') return;
    if (run.command === 'refine' && implementEnabled) {
      // Clear runId/runDir so the useEffect above knows this is a fresh spawn, not a resume
      setRun({ status: 'running', command: 'implement', progress: 0, runId: undefined, runDir: undefined });
    }
  }, [run.status]);

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

        {/* Right Panel: Phase Status + Gate View tabs */}
        <div className="flex-1 overflow-hidden">
          <RightPanel />
        </div>
      </main>
    </div>
  );
}

export default App;
