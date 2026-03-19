import { describe, it, expect, vi } from 'vitest';
import { render, screen, waitFor, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from '../../src/App';
import { useStore } from '../../src/store';
import { mockCsvContent, mockAmbiguityItem, mockTestabilityItem, stderrLines } from '../fixtures/testData';
import type { PikaExitData } from '../../src/types';

/**
 * Helper: set up IPC mocks that capture stderr/exit callbacks.
 * Returns functions to fire simulated events.
 */
function setupIpcCapture() {
  let stderrCb: ((line: string) => void) | null = null;
  let exitCb: ((data: PikaExitData) => void) | null = null;

  vi.mocked(window.electronAPI.onPikaStderr).mockImplementation((cb) => {
    stderrCb = cb;
    return () => { stderrCb = null; };
  });
  vi.mocked(window.electronAPI.onPikaExit).mockImplementation((cb) => {
    exitCb = cb;
    return () => { exitCb = null; };
  });

  return {
    fireStderr: (line: string) => {
      act(() => { stderrCb?.(line); });
    },
    fireExit: (data: PikaExitData) => {
      act(() => { exitCb?.(data); });
    },
  };
}

/**
 * Helper: prepare store for a run and click start.
 */
async function startRun(user: ReturnType<typeof userEvent.setup>) {
  useStore.setState({
    projectRootPath: '/test/project',
    designSpecPath: '/test/spec.csv',
  });
  vi.mocked(window.electronAPI.readFile).mockResolvedValue(mockCsvContent);

  await user.click(screen.getByText('Start Design Improvement'));

  await waitFor(() => {
    expect(useStore.getState().run.status).toBe('running');
  });
}

describe('Refine flow integration', () => {
  it('happy path: idle → running → completed', async () => {
    const user = userEvent.setup();
    const { fireStderr, fireExit } = setupIpcCapture();
    render(<App />);

    // 1. Start
    await startRun(user);
    expect(window.electronAPI.startRefine).toHaveBeenCalledWith(
      expect.objectContaining({ projectRoot: '/test/project' }),
    );

    // 2. Simulate stderr events
    fireStderr(stderrLines.loadOk);
    await waitFor(() => {
      expect(useStore.getState().phases.find((p) => p.id === 'R1')?.status).toBe('done');
    });

    fireStderr(stderrLines.decompRunning);
    await waitFor(() => {
      expect(useStore.getState().phases.find((p) => p.id === 'R2')?.status).toBe('running');
    });

    fireStderr(stderrLines.decompDone);
    await waitFor(() => {
      expect(useStore.getState().phases.find((p) => p.id === 'R2')?.status).toBe('done');
    });

    fireStderr(stderrLines.agentsRunning);
    await waitFor(() => {
      expect(useStore.getState().phases.find((p) => p.id === 'R3')?.status).toBe('running');
      expect(useStore.getState().phases.find((p) => p.id === 'R4')?.status).toBe('running');
    });

    // 3. Simulate completion exit
    fireExit({ code: 0, summary: { status: 'completed' } });
    await waitFor(() => {
      const state = useStore.getState();
      expect(state.run.status).toBe('completed');
      expect(state.run.progress).toBe(100);
      expect(state.phases.find((p) => p.id === 'R1')?.status).toBe('done');
      expect(state.phases.find((p) => p.id === 'R2')?.status).toBe('done');
      expect(state.phases.find((p) => p.id === 'R3')?.status).toBe('done');
      expect(state.phases.find((p) => p.id === 'R4')?.status).toBe('done');
    });
  });

  it('blocked path: idle → running → paused (gate items loaded)', async () => {
    const user = userEvent.setup();
    const { fireStderr, fireExit } = setupIpcCapture();

    // Mock readGateOutput to return test items
    vi.mocked(window.electronAPI.readGateOutput).mockResolvedValue({
      stage: 'agents',
      items: [mockAmbiguityItem, mockTestabilityItem] as never[],
    });

    render(<App />);
    await startRun(user);

    // Simulate some progress
    fireStderr(stderrLines.loadOk);
    fireStderr(stderrLines.decompDone);
    fireStderr(stderrLines.agentsRunning);

    // Simulate blocked exit
    fireExit({
      code: 0,
      summary: { status: 'blocked', run_id: 'test-run-123' },
    });

    await waitFor(() => {
      const state = useStore.getState();
      expect(state.run.status).toBe('paused');
      expect(state.run.runId).toBe('test-run-123');
      expect(state.currentGateItems).toHaveLength(2);
    });

    // Verify GatePanel is visible
    await waitFor(() => {
      expect(screen.getByText(/Ambiguity & Testability Review/)).toBeInTheDocument();
    });
  });

  it('cancel during run: running → failed', async () => {
    const user = userEvent.setup();
    setupIpcCapture();
    render(<App />);
    await startRun(user);

    // Click cancel
    await user.click(screen.getByText('Cancel Run'));
    expect(window.electronAPI.cancelPika).toHaveBeenCalled();
    expect(useStore.getState().run.status).toBe('failed');
  });

  it('settings navigation: idle → settings → back → idle', async () => {
    const user = userEvent.setup();
    render(<App />);

    // Should show EntryScreen initially
    expect(screen.getByText('Start Design Improvement')).toBeInTheDocument();

    // Click gear icon
    await user.click(screen.getByTitle('Settings'));
    await waitFor(() => {
      expect(useStore.getState().view).toBe('settings');
      expect(screen.getByText('Settings')).toBeInTheDocument();
    });

    // Click back
    const buttons = screen.getAllByRole('button');
    await user.click(buttons[0]); // Back arrow
    await waitFor(() => {
      expect(useStore.getState().view).toBe('main');
      expect(screen.getByText('Start Design Improvement')).toBeInTheDocument();
    });
  });
});
