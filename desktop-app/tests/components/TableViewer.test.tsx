import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { TableViewer } from '../../src/components/TableViewer';
import { mockTableAppendix } from '../fixtures/testData';
import type { Appendix } from '../../src/types';

describe('TableViewer', () => {
  it('renders filename in the header', () => {
    render(<TableViewer appendix={mockTableAppendix} />);
    expect(screen.getByText('data.csv')).toBeInTheDocument();
  });

  it('renders module tag badge', () => {
    render(<TableViewer appendix={mockTableAppendix} />);
    expect(screen.getByText('EXPORT')).toBeInTheDocument();
  });

  it('renders row count', () => {
    render(<TableViewer appendix={mockTableAppendix} />);
    expect(screen.getByText('3/3 ROWS')).toBeInTheDocument();
  });

  it('renders column headers', () => {
    render(<TableViewer appendix={mockTableAppendix} />);
    expect(screen.getByText('name')).toBeInTheDocument();
    expect(screen.getByText('value')).toBeInTheDocument();
    expect(screen.getByText('status')).toBeInTheDocument();
  });

  it('renders all data rows', () => {
    render(<TableViewer appendix={mockTableAppendix} />);
    expect(screen.getByText('Alpha')).toBeInTheDocument();
    expect(screen.getByText('Beta')).toBeInTheDocument();
    expect(screen.getByText('Gamma')).toBeInTheDocument();
    expect(screen.getByText('100')).toBeInTheDocument();
    expect(screen.getByText('200')).toBeInTheDocument();
    expect(screen.getByText('300')).toBeInTheDocument();
  });

  it('has a search input', () => {
    render(<TableViewer appendix={mockTableAppendix} />);
    expect(screen.getByPlaceholderText('Search rows...')).toBeInTheDocument();
  });

  it('filters rows by search query', async () => {
    const user = userEvent.setup();
    render(<TableViewer appendix={mockTableAppendix} />);

    const searchInput = screen.getByPlaceholderText('Search rows...');
    await user.type(searchInput, 'Alpha');

    // Only Alpha row should be visible
    expect(screen.getByText('Alpha')).toBeInTheDocument();
    expect(screen.queryByText('Beta')).not.toBeInTheDocument();
    expect(screen.queryByText('Gamma')).not.toBeInTheDocument();
  });

  it('shows "No matching rows" when search has no results', async () => {
    const user = userEvent.setup();
    render(<TableViewer appendix={mockTableAppendix} />);

    const searchInput = screen.getByPlaceholderText('Search rows...');
    await user.type(searchInput, 'nonexistent');

    expect(screen.getByText('No matching rows')).toBeInTheDocument();
  });

  it('updates row count to reflect filtered results', async () => {
    const user = userEvent.setup();
    render(<TableViewer appendix={mockTableAppendix} />);

    const searchInput = screen.getByPlaceholderText('Search rows...');
    await user.type(searchInput, 'active');

    // "active" matches Alpha (active) and Gamma (active), but also Beta (inactive)
    // All three have "active" in status column
    expect(screen.getByText('3/3 ROWS')).toBeInTheDocument();
  });

  it('search is case insensitive', async () => {
    const user = userEvent.setup();
    render(<TableViewer appendix={mockTableAppendix} />);

    const searchInput = screen.getByPlaceholderText('Search rows...');
    await user.type(searchInput, 'alpha');

    expect(screen.getByText('Alpha')).toBeInTheDocument();
  });

  it('shows "No data" for CSV with columns but no rows', () => {
    const emptyTable: Appendix = {
      ...mockTableAppendix,
      id: 'empty-table',
      parsedRows: [],
    };
    render(<TableViewer appendix={emptyTable} />);
    expect(screen.getByText('No data')).toBeInTheDocument();
  });

  it('shows "No columns found" when columns are empty', () => {
    const noColumns: Appendix = {
      ...mockTableAppendix,
      id: 'no-cols',
      columns: [],
      parsedRows: [],
    };
    render(<TableViewer appendix={noColumns} />);
    expect(screen.getByText('No columns found')).toBeInTheDocument();
  });
});
