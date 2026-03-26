import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { AppendixViewer } from '../../src/components/AppendixViewer';
import { useStore } from '../../src/store';
import { mockTextAppendix, mockTableAppendix } from '../fixtures/testData';

describe('AppendixViewer', () => {
  it('renders nothing when appendix ID is not found', () => {
    const { container } = render(<AppendixViewer appendixId="nonexistent" />);
    expect(container.innerHTML).toBe('');
  });

  it('renders PlainTextViewer for text appendix', () => {
    useStore.setState({ appendixes: [mockTextAppendix] });
    render(<AppendixViewer appendixId="appx-text-001" />);

    // PlainTextViewer shows the content in a <pre>
    expect(screen.getByText(/Line one of notes/)).toBeInTheDocument();
    expect(screen.getByText('notes.txt')).toBeInTheDocument();
  });

  it('renders TableViewer for table appendix', () => {
    useStore.setState({ appendixes: [mockTableAppendix] });
    render(<AppendixViewer appendixId="appx-table-001" />);

    // TableViewer shows column headers and data
    expect(screen.getByText('name')).toBeInTheDocument();
    expect(screen.getByText('Alpha')).toBeInTheDocument();
    expect(screen.getByText('data.csv')).toBeInTheDocument();
  });
});
