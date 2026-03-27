import { describe, it, expect } from 'vitest';
import { buildAppendixFromContent } from '../../src/services/appendixLoader';
import type { AppendixRef } from '../../src/types';

const textRef: AppendixRef = {
  id: 'ref-text',
  fileName: 'notes.txt',
  filePath: '/test/notes.txt',
  type: 'text',
  moduleTag: 'AUTH',
};

const tableRef: AppendixRef = {
  id: 'ref-table',
  fileName: 'data.csv',
  filePath: '/test/data.csv',
  type: 'table',
  moduleTag: 'EXPORT',
};

describe('buildAppendixFromContent', () => {
  it('builds text appendix with content only', () => {
    const result = buildAppendixFromContent(textRef, 'Hello\nWorld');
    expect(result.id).toBe('ref-text');
    expect(result.content).toBe('Hello\nWorld');
    expect(result.type).toBe('text');
    expect(result.parsedRows).toBeUndefined();
    expect(result.columns).toBeUndefined();
  });

  it('builds table appendix with parsed rows and columns', () => {
    const csv = 'name,value\nAlpha,100\nBeta,200';
    const result = buildAppendixFromContent(tableRef, csv);
    expect(result.id).toBe('ref-table');
    expect(result.content).toBe(csv);
    expect(result.columns).toEqual(['name', 'value']);
    expect(result.parsedRows).toEqual([
      { name: 'Alpha', value: '100' },
      { name: 'Beta', value: '200' },
    ]);
  });

  it('handles empty CSV content', () => {
    const result = buildAppendixFromContent(tableRef, '');
    expect(result.columns).toEqual([]);
    expect(result.parsedRows).toEqual([]);
  });

  it('handles CSV with headers only', () => {
    const result = buildAppendixFromContent(tableRef, 'col_a,col_b');
    expect(result.columns).toEqual(['col_a', 'col_b']);
    expect(result.parsedRows).toEqual([]);
  });

  it('preserves ref fields in output', () => {
    const result = buildAppendixFromContent(textRef, 'content');
    expect(result.fileName).toBe('notes.txt');
    expect(result.filePath).toBe('/test/notes.txt');
    expect(result.moduleTag).toBe('AUTH');
  });
});
