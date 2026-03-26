import { describe, it, expect, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { EntryScreen } from '../../src/components/EntryScreen';
import { useStore } from '../../src/store';
import { mockCsvContent, mockAppendixCsvContent } from '../fixtures/testData';

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

  describe('Appendixes section', () => {
    it('renders the Appendixes section label', () => {
      render(<EntryScreen />);
      expect(screen.getByText('Appendixes')).toBeInTheDocument();
    });

    it('shows empty state message when no appendixes', () => {
      render(<EntryScreen />);
      expect(screen.getByText(/Import reference files/)).toBeInTheDocument();
    });

    it('appendix section is visually disabled when no design spec selected', () => {
      render(<EntryScreen />);
      const addButton = screen.getByText('Add');
      // The section has pointer-events-none when no spec
      expect(addButton.closest('section')).toHaveClass('pointer-events-none');
    });

    it('appendix section is enabled when design spec is selected', () => {
      useStore.setState({ designSpecPath: '/test/spec.csv' });
      render(<EntryScreen />);
      const addButton = screen.getByText('Add');
      expect(addButton.closest('section')).not.toHaveClass('pointer-events-none');
    });

    it('browse design spec eagerly parses module tags', async () => {
      const user = userEvent.setup();
      vi.mocked(window.electronAPI.openFileDialog).mockResolvedValue('/test/spec.csv');
      vi.mocked(window.electronAPI.readFile).mockResolvedValue(mockCsvContent);
      render(<EntryScreen />);

      const browseButtons = screen.getAllByText('Browse...');
      await user.click(browseButtons[1]); // Design spec browse

      await waitFor(() => {
        const tags = useStore.getState().availableModuleTags;
        expect(tags).toContain('AUTH');
        expect(tags).toContain('EXPORT');
      });
    });

    it('changing design spec clears existing appendixes', async () => {
      const user = userEvent.setup();
      // Pre-populate an appendix
      useStore.setState({
        designSpecPath: '/test/old-spec.csv',
        appendixes: [{
          id: 'old-appx',
          fileName: 'old.txt',
          filePath: '/test/old.txt',
          type: 'text',
          moduleTag: 'AUTH',
          content: 'old content',
        }],
      });
      vi.mocked(window.electronAPI.openFileDialog).mockResolvedValue('/test/new-spec.csv');
      vi.mocked(window.electronAPI.readFile).mockResolvedValue(mockCsvContent);
      render(<EntryScreen />);

      const browseButtons = screen.getAllByText('Browse...');
      await user.click(browseButtons[1]);

      await waitFor(() => {
        expect(useStore.getState().appendixes).toHaveLength(0);
      });
    });

    it('Add button opens file dialog and adds text appendix', async () => {
      const user = userEvent.setup();
      useStore.setState({
        designSpecPath: '/test/spec.csv',
        availableModuleTags: ['AUTH', 'EXPORT'],
      });
      vi.mocked(window.electronAPI.openFileDialog).mockResolvedValue('/test/notes.txt');
      vi.mocked(window.electronAPI.readFile).mockResolvedValue('Some plain text content');
      render(<EntryScreen />);

      await user.click(screen.getByText('Add'));

      await waitFor(() => {
        const appxs = useStore.getState().appendixes;
        expect(appxs).toHaveLength(1);
        expect(appxs[0].type).toBe('text');
        expect(appxs[0].fileName).toBe('notes.txt');
        expect(appxs[0].moduleTag).toBe('AUTH'); // defaults to first tag
        expect(appxs[0].content).toBe('Some plain text content');
      });
    });

    it('Add button opens file dialog and adds CSV appendix with parsed data', async () => {
      const user = userEvent.setup();
      useStore.setState({
        designSpecPath: '/test/spec.csv',
        availableModuleTags: ['AUTH', 'EXPORT'],
      });
      vi.mocked(window.electronAPI.openFileDialog).mockResolvedValue('/test/data.csv');
      vi.mocked(window.electronAPI.readFile).mockResolvedValue(mockAppendixCsvContent);
      render(<EntryScreen />);

      await user.click(screen.getByText('Add'));

      await waitFor(() => {
        const appxs = useStore.getState().appendixes;
        expect(appxs).toHaveLength(1);
        expect(appxs[0].type).toBe('table');
        expect(appxs[0].fileName).toBe('data.csv');
        expect(appxs[0].columns).toEqual(['name', 'value', 'status']);
        expect(appxs[0].parsedRows).toHaveLength(3);
        expect(appxs[0].parsedRows![0].name).toBe('Alpha');
      });
    });

    it('does not add appendix when file dialog is cancelled', async () => {
      const user = userEvent.setup();
      useStore.setState({
        designSpecPath: '/test/spec.csv',
        availableModuleTags: ['AUTH'],
      });
      vi.mocked(window.electronAPI.openFileDialog).mockResolvedValue(null);
      render(<EntryScreen />);

      await user.click(screen.getByText('Add'));

      // Wait a tick, then verify no appendix was added
      await waitFor(() => {
        expect(useStore.getState().appendixes).toHaveLength(0);
      });
    });

    it('renders imported appendix list items with filename and type badge', async () => {
      useStore.setState({
        designSpecPath: '/test/spec.csv',
        availableModuleTags: ['AUTH', 'EXPORT'],
        appendixes: [
          {
            id: 'a1',
            fileName: 'notes.txt',
            filePath: '/test/notes.txt',
            type: 'text',
            moduleTag: 'AUTH',
            content: 'text content',
          },
          {
            id: 'a2',
            fileName: 'data.csv',
            filePath: '/test/data.csv',
            type: 'table',
            moduleTag: 'EXPORT',
            content: 'csv content',
            columns: ['col1'],
            parsedRows: [{ col1: 'val' }],
          },
        ],
      });
      render(<EntryScreen />);

      expect(screen.getByText('notes.txt')).toBeInTheDocument();
      expect(screen.getByText('data.csv')).toBeInTheDocument();
      expect(screen.getByText('text')).toBeInTheDocument();
      expect(screen.getByText('table')).toBeInTheDocument();
    });

    it('remove button removes the appendix', async () => {
      const user = userEvent.setup();
      useStore.setState({
        designSpecPath: '/test/spec.csv',
        availableModuleTags: ['AUTH'],
        appendixes: [{
          id: 'a1',
          fileName: 'notes.txt',
          filePath: '/test/notes.txt',
          type: 'text',
          moduleTag: 'AUTH',
          content: 'text',
        }],
      });
      render(<EntryScreen />);

      expect(screen.getByText('notes.txt')).toBeInTheDocument();

      // Click the X remove button
      const removeButtons = screen.getAllByRole('button').filter(
        (btn) => btn.querySelector('svg.lucide-x')
      );
      expect(removeButtons).toHaveLength(1);
      await user.click(removeButtons[0]);

      await waitFor(() => {
        expect(useStore.getState().appendixes).toHaveLength(0);
      });
    });

    it('module tag dropdown changes the appendix module tag', async () => {
      const user = userEvent.setup();
      useStore.setState({
        designSpecPath: '/test/spec.csv',
        availableModuleTags: ['AUTH', 'EXPORT'],
        appendixes: [{
          id: 'a1',
          fileName: 'notes.txt',
          filePath: '/test/notes.txt',
          type: 'text',
          moduleTag: 'AUTH',
          content: 'text',
        }],
      });
      render(<EntryScreen />);

      const select = screen.getByDisplayValue('AUTH');
      await user.selectOptions(select, 'EXPORT');

      await waitFor(() => {
        expect(useStore.getState().appendixes[0].moduleTag).toBe('EXPORT');
      });
    });

    it('shows error when appendix file read fails', async () => {
      const user = userEvent.setup();
      useStore.setState({
        designSpecPath: '/test/spec.csv',
        availableModuleTags: ['AUTH'],
      });
      vi.mocked(window.electronAPI.openFileDialog).mockResolvedValue('/test/bad.txt');
      vi.mocked(window.electronAPI.readFile).mockRejectedValue(new Error('File not found'));
      render(<EntryScreen />);

      await user.click(screen.getByText('Add'));

      await waitFor(() => {
        expect(screen.getByText(/Failed to load appendix/)).toBeInTheDocument();
      });
    });
  });
});
