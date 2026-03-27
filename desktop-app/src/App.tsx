import { useEffect, useRef, useState, useCallback } from 'react';
import { TopBar } from './components/TopBar';
import { LeftPanel } from './components/LeftPanel';
import { PipelineView } from './components/PipelineView';
import { GatePanel } from './components/GatePanel';
import { EntryScreen } from './components/EntryScreen';
import { SettingsPage } from './components/SettingsPage';
import { useStore } from './store';
import {
  parseStderrLine,
  mapStderrToPhaseUpdates,
  computeProgress,
  transformAgentItems,
} from './services/pikaService';
import type { RawAgentItem } from './types';

function App() {
  const {
    run, setRun, updatePhase,
    setCurrentGateItems, setActiveItemIndex,
    designSpecPath, projectRootPath, configPath,
    view,
  } = useStore();

  const cleanupRef = useRef<(() => void) | null>(null);

  // Start refine process when run status transitions to 'running' and no process is active
  useEffect(() => {
    if (run.status !== 'running' || !projectRootPath) return;

    // Avoid re-triggering if we already have listeners (e.g. after gate resume)
    if (cleanupRef.current) return;

    const startRefine = async () => {
      try {
        await window.electronAPI.startRefine({
          projectRoot: projectRootPath,
          designSpecPath: designSpecPath ?? undefined,
          configPath: configPath ?? undefined,
        });
      } catch (err) {
        setRun({ status: 'failed' });
        return;
      }

      const unsubStderr = window.electronAPI.onPikaStderr((line: string) => {
        const event = parseStderrLine(line);
        if (!event) return;

        const updates = mapStderrToPhaseUpdates(event);
        for (const { phaseId, status } of updates) {
          updatePhase(phaseId, { status });
        }

        // Update progress based on current phase states
        const currentPhases = useStore.getState().phases;
        setRun({ progress: computeProgress(currentPhases) });
      });

      const unsubExit = window.electronAPI.onPikaExit(async (data) => {
        const { summary } = data;
        const status = summary?.status as string | undefined;

        if (status === 'completed') {
          // Mark all refine phases done
          for (const id of ['R1', 'R2', 'R3', 'R4']) {
            updatePhase(id, { status: 'done' });
          }
          setRun({ status: 'completed', progress: 100 });
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
              );
              setCurrentGateItems(items);
              setActiveItemIndex(0);
              setRun({ status: 'paused', runDir, runId });
            } catch {
              setRun({ status: 'failed' });
            }
          } else {
            setRun({ status: 'failed' });
          }
        } else {
          setRun({ status: 'failed' });
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
