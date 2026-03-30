import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { PipelineView } from '../../src/components/PipelineView';
import { useStore } from '../../src/store';

describe('PipelineView', () => {
  it('renders all three phase groups', () => {
    render(<PipelineView />);
    expect(screen.getByText('Refine')).toBeInTheDocument();
    expect(screen.getByText('Implement')).toBeInTheDocument();
    expect(screen.getAllByText('Batch Execution').length).toBeGreaterThanOrEqual(1);
  });

  it('renders refine phase names', () => {
    render(<PipelineView />);
    expect(screen.getByText('Load & Validate Spec')).toBeInTheDocument();
    expect(screen.getByText('Decomposition Check')).toBeInTheDocument();
    expect(screen.getByText('Ambiguity Detection')).toBeInTheDocument();
    expect(screen.getByText('Testability Audit')).toBeInTheDocument();
  });

  it('renders implement phase names', () => {
    render(<PipelineView />);
    expect(screen.getByText('Normalize Config')).toBeInTheDocument();
    expect(screen.getByText('Run Unified Planner')).toBeInTheDocument();
    expect(screen.getByText('Gate: Planner Blockers')).toBeInTheDocument();
    expect(screen.getByText('Construct Batch Plan')).toBeInTheDocument();
  });

  it('shows [PENDING] for all phases initially', () => {
    render(<PipelineView />);
    const pendingLabels = screen.getAllByText('[PENDING]');
    // 4 refine + 4 implement + 1 batch = 9
    expect(pendingLabels.length).toBeGreaterThanOrEqual(9);
  });

  it('shows [DONE] when a phase is done', () => {
    useStore.getState().updatePhase('R1', { status: 'done' });
    render(<PipelineView />);
    expect(screen.getByText('[DONE]')).toBeInTheDocument();
  });

  it('shows [RUNNING] when a phase is running', () => {
    useStore.getState().updatePhase('R2', { status: 'running' });
    render(<PipelineView />);
    expect(screen.getByText('[RUNNING]')).toBeInTheDocument();
  });

  it('shows [BLOCKED] when a phase is blocked', () => {
    useStore.getState().updatePhase('R2', { status: 'blocked' });
    render(<PipelineView />);
    expect(screen.getByText('[BLOCKED]')).toBeInTheDocument();
  });

  it('shows [FAILED] when a phase is failed', () => {
    useStore.getState().updatePhase('R1', { status: 'failed' });
    render(<PipelineView />);
    expect(screen.getByText('[FAILED]')).toBeInTheDocument();
  });

  it('shows [RUNNING] for implement phase when running', () => {
    useStore.getState().updatePhase('I5', { status: 'running' });
    render(<PipelineView />);
    expect(screen.getByText('[RUNNING]')).toBeInTheDocument();
  });

  it('shows [BLOCKED] for implement phase when blocked', () => {
    useStore.getState().updatePhase('I7', { status: 'blocked' });
    render(<PipelineView />);
    expect(screen.getByText('[BLOCKED]')).toBeInTheDocument();
  });

  it('shows actual status for batch phase', () => {
    useStore.getState().updatePhase('B-EXEC', { status: 'running' });
    render(<PipelineView />);
    const runningLabels = screen.getAllByText('[RUNNING]');
    expect(runningLabels.length).toBeGreaterThanOrEqual(1);
  });
});
