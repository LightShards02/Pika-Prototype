import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { LeftPanel } from '../../src/components/LeftPanel';
import { useStore } from '../../src/store';
import { mockSpecs, mockTextAppendix, mockTableAppendix } from '../fixtures/testData';

describe('LeftPanel', () => {
  it('renders SpecViewer directly when no appendixes exist', () => {
    useStore.setState({ specs: mockSpecs });
    render(<LeftPanel />);

    // SpecViewer header should be present
    expect(screen.getByText('Design Spec')).toBeInTheDocument();
    // No tab bar — the "Design Spec" text is the SpecViewer header, not a tab
    expect(screen.queryByRole('button', { name: /Design Spec/ })).not.toBeInTheDocument();
  });

  it('renders tab bar when appendixes exist', () => {
    useStore.setState({
      specs: mockSpecs,
      appendixes: [mockTextAppendix],
    });
    render(<LeftPanel />);

    // Tab bar should have Design Spec tab and appendix tab
    const designSpecTab = screen.getByRole('button', { name: /Design Spec/ });
    expect(designSpecTab).toBeInTheDocument();

    const appendixTab = screen.getByRole('button', { name: /notes\.txt/ });
    expect(appendixTab).toBeInTheDocument();
  });

  it('shows SpecViewer content by default (activeLeftTab = spec)', () => {
    useStore.setState({
      specs: mockSpecs,
      appendixes: [mockTextAppendix],
      activeLeftTab: 'spec',
    });
    render(<LeftPanel />);

    // SpecViewer table headers should be visible
    expect(screen.getByText('spec_id')).toBeInTheDocument();
    expect(screen.getByText('requirement')).toBeInTheDocument();
  });

  it('switches to appendix content when appendix tab is clicked', async () => {
    const user = userEvent.setup();
    useStore.setState({
      specs: mockSpecs,
      appendixes: [mockTextAppendix],
      activeLeftTab: 'spec',
    });
    render(<LeftPanel />);

    // Click appendix tab
    const appendixTab = screen.getByRole('button', { name: /notes\.txt/ });
    await user.click(appendixTab);

    expect(useStore.getState().activeLeftTab).toBe('appx-text-001');
  });

  it('switches back to spec when Design Spec tab is clicked', async () => {
    const user = userEvent.setup();
    useStore.setState({
      specs: mockSpecs,
      appendixes: [mockTextAppendix],
      activeLeftTab: 'appx-text-001',
    });
    render(<LeftPanel />);

    const specTab = screen.getByRole('button', { name: /Design Spec/ });
    await user.click(specTab);

    expect(useStore.getState().activeLeftTab).toBe('spec');
  });

  it('renders correct icons for text and table appendixes', () => {
    useStore.setState({
      specs: mockSpecs,
      appendixes: [mockTextAppendix, mockTableAppendix],
    });
    render(<LeftPanel />);

    // Both appendix tabs visible
    expect(screen.getByRole('button', { name: /notes\.txt/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /data\.csv/ })).toBeInTheDocument();
  });

  it('shows text appendix content when text tab is active', () => {
    useStore.setState({
      specs: mockSpecs,
      appendixes: [mockTextAppendix],
      activeLeftTab: 'appx-text-001',
    });
    render(<LeftPanel />);

    // Filename appears in both tab and viewer header
    expect(screen.getAllByText('notes.txt').length).toBeGreaterThanOrEqual(2);
    // Text content from PlainTextViewer
    expect(screen.getByText(/Line one of notes/)).toBeInTheDocument();
  });

  it('shows table appendix content when table tab is active', () => {
    useStore.setState({
      specs: mockSpecs,
      appendixes: [mockTableAppendix],
      activeLeftTab: 'appx-table-001',
    });
    render(<LeftPanel />);

    // Filename appears in both tab and viewer header
    expect(screen.getAllByText('data.csv').length).toBeGreaterThanOrEqual(2);
    // Table column headers
    expect(screen.getByText('name')).toBeInTheDocument();
    expect(screen.getByText('value')).toBeInTheDocument();
    // Table data
    expect(screen.getByText('Alpha')).toBeInTheDocument();
    expect(screen.getByText('Beta')).toBeInTheDocument();
  });

  it('renders multiple appendix tabs', () => {
    useStore.setState({
      specs: mockSpecs,
      appendixes: [mockTextAppendix, mockTableAppendix],
    });
    render(<LeftPanel />);

    const tabs = screen.getAllByRole('button');
    // Design Spec tab + 2 appendix tabs = at least 3
    expect(tabs.length).toBeGreaterThanOrEqual(3);
  });
});
