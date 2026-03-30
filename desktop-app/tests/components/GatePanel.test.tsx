import { describe, it, expect, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { GatePanel } from '../../src/components/GatePanel';
import { useStore } from '../../src/store';
import { buildGateItems } from '../fixtures/testData';

function setupGateState() {
  const items = buildGateItems();
  useStore.setState({
    currentGateItems: items,
    activeItemIndex: 0,
    run: {
      currentPhaseId: 'R3',
      progress: 75,
      status: 'paused',
      command: 'refine',
      runDir: '/test/run/dir',
      runId: 'test-run',
      projectRoot: '/test/project',
    },
  });
  return items;
}

describe('GatePanel', () => {
  it('renders current item type and reason', () => {
    setupGateState();
    render(<GatePanel />);
    expect(screen.getByText(/Ambiguity: Vague authentication/)).toBeInTheDocument();
    // "authenticate users" appears in multiple places (currentText, reason, suggestion)
    expect(screen.getAllByText(/authenticate users/).length).toBeGreaterThanOrEqual(1);
  });

  it('renders suggested text', () => {
    setupGateState();
    render(<GatePanel />);
    expect(screen.getByText(/OAuth2 with PKCE flow/)).toBeInTheDocument();
  });

  it('renders option buttons', () => {
    setupGateState();
    render(<GatePanel />);
    expect(screen.getByText('Accept Suggestion')).toBeInTheDocument();
    expect(screen.getByText('Let Agent Edit')).toBeInTheDocument();
    expect(screen.getByText('Skip')).toBeInTheDocument();
  });

  it('renders item counter', () => {
    setupGateState();
    render(<GatePanel />);
    expect(screen.getByText(/ITEM 1 OF 2/)).toBeInTheDocument();
  });

  it('option click resolves item in store', async () => {
    const user = userEvent.setup();
    setupGateState();
    render(<GatePanel />);

    await user.click(screen.getByText('Accept Suggestion'));
    const items = useStore.getState().currentGateItems;
    expect(items[0].selectedOption).toBe('accept_suggestion');
  });

  it('next button advances to next item', async () => {
    const user = userEvent.setup();
    setupGateState();
    render(<GatePanel />);

    await user.click(screen.getByText('Next Item'));
    expect(useStore.getState().activeItemIndex).toBe(1);
  });

  it('previous button is disabled on first item', () => {
    setupGateState();
    render(<GatePanel />);
    const prevButton = screen.getByText('Previous Item');
    expect(prevButton.closest('button')).toBeDisabled();
  });

  it('next button is disabled on last item', () => {
    setupGateState();
    useStore.setState({ activeItemIndex: 1 });
    render(<GatePanel />);
    const nextButton = screen.getByText('Next Item');
    expect(nextButton.closest('button')).toBeDisabled();
  });

  it('continue button is disabled when not all items resolved', () => {
    setupGateState();
    render(<GatePanel />);
    expect(screen.getByText('Continue')).toBeInTheDocument();
    expect(screen.getByText('Continue').closest('button')).toBeDisabled();
  });

  it('continue button is enabled when all items resolved', () => {
    setupGateState();
    const items = useStore.getState().currentGateItems.map((item) => ({
      ...item,
      selectedOption: 'accept_suggestion',
    }));
    useStore.setState({ currentGateItems: items });
    render(<GatePanel />);
    expect(screen.getByText('Continue').closest('button')).not.toBeDisabled();
  });

  it('shows resolution progress', () => {
    setupGateState();
    render(<GatePanel />);
    expect(screen.getByText('0 / 2 resolved')).toBeInTheDocument();
  });

  it('continue triggers write + apply + resume flow', async () => {
    const user = userEvent.setup();
    setupGateState();

    // Resolve all items
    const items = useStore.getState().currentGateItems.map((item) => ({
      ...item,
      selectedOption: 'accept_suggestion',
    }));
    useStore.setState({ currentGateItems: items });

    // Mock onPikaExit to capture callback and simulate exit
    let exitCb: ((data: { code: number; summary: Record<string, unknown> | null }) => void) | null = null;
    vi.mocked(window.electronAPI.onPikaExit).mockImplementation((cb) => {
      exitCb = cb;
      return () => { exitCb = null; };
    });

    render(<GatePanel />);
    await user.click(screen.getByText('Continue'));

    await waitFor(() => {
      expect(window.electronAPI.writeResolution).toHaveBeenCalledWith(
        expect.objectContaining({ runDir: '/test/run/dir' }),
      );
    });

    // Simulate the apply exit so the flow continues
    if (exitCb) {
      exitCb({ code: 0, summary: { status: 'completed' } });
    }

    await waitFor(() => {
      expect(window.electronAPI.applyResolutions).toHaveBeenCalledWith(
        expect.objectContaining({ projectRoot: '/test/project', runId: 'test-run' }),
      );
    });
  });
});
