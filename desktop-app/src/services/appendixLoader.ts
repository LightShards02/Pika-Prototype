import Papa from 'papaparse';
import type { Appendix, AppendixRef } from '../types';

/**
 * Construct a full Appendix from an AppendixRef and its file content.
 * For CSV files, parses into columns and parsedRows.
 */
export function buildAppendixFromContent(ref: AppendixRef, content: string): Appendix {
  const appendix: Appendix = {
    ...ref,
    content,
  };

  if (ref.type === 'table') {
    const parsed = Papa.parse<Record<string, string>>(content, {
      header: true,
      skipEmptyLines: true,
    });
    appendix.columns = parsed.meta.fields ?? [];
    appendix.parsedRows = parsed.data;
  }

  return appendix;
}
