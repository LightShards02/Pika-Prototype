import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SpecViewer } from '../../src/components/SpecViewer';
import { useStore } from '../../src/store';
import { mockSpecs } from '../fixtures/testData';

describe('SpecViewer', () => {
  it('renders spec rows from store', () => {
    useStore.setState({ specs: mockSpecs });
    render(<SpecViewer />);
    expect(screen.getByText('SPEC-001')).toBeInTheDocument();
    expect(screen.getByText('SPEC-002')).toBeInTheDocument();
    expect(screen.getByText('AUTH')).toBeInTheDocument();
    expect(screen.getByText('EXPORT')).toBeInTheDocument();
  });

  it('shows spec count badge', () => {
    useStore.setState({ specs: mockSpecs });
    render(<SpecViewer />);
    expect(screen.getByText(/2\/2 SPECS/)).toBeInTheDocument();
  });

  it('renders empty table when no specs', () => {
    useStore.setState({ specs: [] });
    render(<SpecViewer />);
    expect(screen.getByText(/0\/0 SPECS/)).toBeInTheDocument();
    expect(screen.queryByText('SPEC-001')).not.toBeInTheDocument();
  });

  it('filters specs by search query', async () => {
    const user = userEvent.setup();
    useStore.setState({ specs: mockSpecs });
    render(<SpecViewer />);

    const searchInput = screen.getByPlaceholderText('Search specs...');
    await user.type(searchInput, 'AUTH');

    expect(screen.getByText('SPEC-001')).toBeInTheDocument();
    expect(screen.queryByText('SPEC-002')).not.toBeInTheDocument();
  });

  it('filters specs by requirement text', async () => {
    const user = userEvent.setup();
    useStore.setState({ specs: mockSpecs });
    render(<SpecViewer />);

    const searchInput = screen.getByPlaceholderText('Search specs...');
    await user.type(searchInput, 'export');

    expect(screen.queryByText('SPEC-001')).not.toBeInTheDocument();
    expect(screen.getByText('SPEC-002')).toBeInTheDocument();
  });

  it('shows all specs when search is cleared', async () => {
    const user = userEvent.setup();
    useStore.setState({ specs: mockSpecs });
    render(<SpecViewer />);

    const searchInput = screen.getByPlaceholderText('Search specs...');
    await user.type(searchInput, 'AUTH');
    await user.clear(searchInput);

    expect(screen.getByText('SPEC-001')).toBeInTheDocument();
    expect(screen.getByText('SPEC-002')).toBeInTheDocument();
  });
});
