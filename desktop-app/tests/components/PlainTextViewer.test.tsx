import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { PlainTextViewer } from '../../src/components/PlainTextViewer';
import { mockTextAppendix } from '../fixtures/testData';
import type { Appendix } from '../../src/types';

describe('PlainTextViewer', () => {
  it('renders filename in the header', () => {
    render(<PlainTextViewer appendix={mockTextAppendix} />);
    expect(screen.getByText('notes.txt')).toBeInTheDocument();
  });

  it('renders module tag badge', () => {
    render(<PlainTextViewer appendix={mockTextAppendix} />);
    expect(screen.getByText('AUTH')).toBeInTheDocument();
  });

  it('renders line count', () => {
    render(<PlainTextViewer appendix={mockTextAppendix} />);
    // "Line one\nLine two\nLine three" = 3 lines
    expect(screen.getByText('3 lines')).toBeInTheDocument();
  });

  it('renders the text content', () => {
    render(<PlainTextViewer appendix={mockTextAppendix} />);
    expect(screen.getByText(/Line one of notes/)).toBeInTheDocument();
    expect(screen.getByText(/Line two of notes/)).toBeInTheDocument();
    expect(screen.getByText(/Line three of notes/)).toBeInTheDocument();
  });

  it('shows empty file message when content is empty', () => {
    const emptyAppendix: Appendix = {
      ...mockTextAppendix,
      id: 'empty-001',
      content: '',
    };
    render(<PlainTextViewer appendix={emptyAppendix} />);
    expect(screen.getByText('Empty file')).toBeInTheDocument();
  });

  it('renders content in a pre element for monospace formatting', () => {
    render(<PlainTextViewer appendix={mockTextAppendix} />);
    const pre = document.querySelector('pre');
    expect(pre).toBeInTheDocument();
    expect(pre?.textContent).toContain('Line one of notes');
  });
});
