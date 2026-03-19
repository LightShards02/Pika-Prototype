import { describe, it, expect, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { EntryScreen } from '../../src/components/EntryScreen';
import { useStore } from '../../src/store';
import { mockCsvContent } from '../fixtures/testData';

describe('EntryScreen', () => {
  it('renders browse buttons and start button', () => {
    render(<EntryScreen />);
    const browseButtons = screen.getAllByText('Browse...');
    expect(browseButtons.length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText('Start Design Improvement')).toBeInTheDocument();
  });

  it('renders section labels', () => {
    render(<EntryScreen />);
    expect(screen.getByText('Project Root')).toBeInTheDocument();
    expect(screen.getByText('Design Spec')).toBeInTheDocument();
    expect(screen.getByText('Options')).toBeInTheDocument();
  });

  it('renders option checkboxes', () => {
    render(<EntryScreen />);
    expect(screen.getByText('Run Refine')).toBeInTheDocument();
    expect(screen.getByText('Run Implement')).toBeInTheDocument();
    expect(screen.getByText('Decomposition check')).toBeInTheDocument();
  });

  it('browse project root calls openDirDialog', async () => {
    const user = userEvent.setup();
    vi.mocked(window.electronAPI.openDirDialog).mockResolvedValue('/test/project');
    render(<EntryScreen />);

    const browseButtons = screen.getAllByText('Browse...');
    await user.click(browseButtons[0]); // First browse = project root

    expect(window.electronAPI.openDirDialog).toHaveBeenCalled();
    await waitFor(() => {
      expect(useStore.getState().projectRootPath).toBe('/test/project');
    });
  });

  it('browse design spec calls openFileDialog with CSV filter', async () => {
    const user = userEvent.setup();
    vi.mocked(window.electronAPI.openFileDialog).mockResolvedValue('/test/spec.csv');
    render(<EntryScreen />);

    const browseButtons = screen.getAllByText('Browse...');
    await user.click(browseButtons[1]); // Second browse = design spec

    expect(window.electronAPI.openFileDialog).toHaveBeenCalledWith(
      expect.objectContaining({
        filters: expect.arrayContaining([
          expect.objectContaining({ extensions: ['csv'] }),
        ]),
      }),
    );
  });

  it('shows error when starting without project root', async () => {
    const user = userEvent.setup();
    render(<EntryScreen />);

    await user.click(screen.getByText('Start Design Improvement'));
    expect(screen.getByText(/Please select a project root/)).toBeInTheDocument();
  });

  it('shows error when starting without design spec', async () => {
    const user = userEvent.setup();
    useStore.setState({ projectRootPath: '/test/project' });
    render(<EntryScreen />);

    await user.click(screen.getByText('Start Design Improvement'));
    expect(screen.getByText(/Please select a design spec/)).toBeInTheDocument();
  });

  it('start button parses CSV and transitions to running', async () => {
    const user = userEvent.setup();
    useStore.setState({ projectRootPath: '/test/project', designSpecPath: '/test/spec.csv' });
    vi.mocked(window.electronAPI.readFile).mockResolvedValue(mockCsvContent);
    render(<EntryScreen />);

    await user.click(screen.getByText('Start Design Improvement'));

    await waitFor(() => {
      const state = useStore.getState();
      expect(state.run.status).toBe('running');
      expect(state.specs).toHaveLength(2);
      expect(state.specs[0].spec_id).toBe('SPEC-001');
      expect(state.specs[1].spec_id).toBe('SPEC-002');
    });
  });
});
