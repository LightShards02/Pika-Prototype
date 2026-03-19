import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { TopBar } from '../../src/components/TopBar';
import { useStore } from '../../src/store';

describe('TopBar', () => {
  it('shows gear icon when idle', () => {
    render(<TopBar />);
    const gearButton = screen.getByTitle('Settings');
    expect(gearButton).toBeInTheDocument();
  });

  it('does not show cancel button when idle', () => {
    render(<TopBar />);
    expect(screen.queryByText('Cancel Run')).not.toBeInTheDocument();
  });

  it('shows Running badge when running', () => {
    useStore.setState({ run: { currentPhaseId: 'R1', progress: 25, status: 'running' } });
    render(<TopBar />);
    expect(screen.getByText('Running')).toBeInTheDocument();
  });

  it('shows progress bar when running', () => {
    useStore.setState({ run: { currentPhaseId: 'R1', progress: 50, status: 'running' } });
    render(<TopBar />);
    expect(screen.getByText('50%')).toBeInTheDocument();
  });

  it('shows cancel button when running', () => {
    useStore.setState({ run: { currentPhaseId: 'R1', progress: 25, status: 'running' } });
    render(<TopBar />);
    expect(screen.getByText('Cancel Run')).toBeInTheDocument();
  });

  it('hides gear icon when running', () => {
    useStore.setState({ run: { currentPhaseId: 'R1', progress: 25, status: 'running' } });
    render(<TopBar />);
    expect(screen.queryByTitle('Settings')).not.toBeInTheDocument();
  });

  it('shows Paused at Gate badge when paused', () => {
    useStore.setState({ run: { currentPhaseId: 'R3', progress: 75, status: 'paused' } });
    render(<TopBar />);
    expect(screen.getByText('Paused at Gate')).toBeInTheDocument();
  });

  it('shows Completed badge when completed', () => {
    useStore.setState({ run: { currentPhaseId: 'R4', progress: 100, status: 'completed' } });
    render(<TopBar />);
    expect(screen.getByText('Completed')).toBeInTheDocument();
  });

  it('shows Failed badge when failed', () => {
    useStore.setState({ run: { currentPhaseId: 'R1', progress: 0, status: 'failed' } });
    render(<TopBar />);
    expect(screen.getByText('Failed')).toBeInTheDocument();
  });

  it('cancel button calls cancelPika and sets status to failed', async () => {
    const user = userEvent.setup();
    useStore.setState({ run: { currentPhaseId: 'R1', progress: 25, status: 'running' } });
    render(<TopBar />);

    await user.click(screen.getByText('Cancel Run'));
    expect(window.electronAPI.cancelPika).toHaveBeenCalled();
    expect(useStore.getState().run.status).toBe('failed');
  });

  it('gear icon navigates to settings', async () => {
    const user = userEvent.setup();
    render(<TopBar />);

    await user.click(screen.getByTitle('Settings'));
    expect(useStore.getState().view).toBe('settings');
  });

  it('back arrow from settings returns to main', async () => {
    const user = userEvent.setup();
    useStore.setState({ view: 'settings' });
    render(<TopBar />);

    // The back arrow is the first button
    const buttons = screen.getAllByRole('button');
    await user.click(buttons[0]); // ArrowLeft button
    expect(useStore.getState().view).toBe('main');
  });
});
