import type { Appendix } from '../types';

export const PlainTextViewer = ({ appendix }: { appendix: Appendix }) => {
  const lineCount = appendix.content.split('\n').length;

  return (
    <div className="flex flex-col h-full bg-bg-panel border-r border-border-subtle overflow-hidden">
      <div className="p-4 border-b border-border-subtle bg-bg-primary">
        <div className="flex items-center justify-between">
          <h2 className="text-[13px] font-semibold text-text-primary truncate" title={appendix.fileName}>
            {appendix.fileName}
          </h2>
          <div className="flex items-center gap-2 shrink-0">
            <span className="px-2 py-0.5 bg-indigo-light text-indigo-mid text-[11px] font-bold rounded">
              {appendix.moduleTag}
            </span>
            <span className="text-[11px] text-text-tertiary">
              {lineCount} lines
            </span>
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-auto p-4">
        {appendix.content ? (
          <pre className="text-[13px] font-mono text-text-secondary whitespace-pre-wrap break-words leading-relaxed">
            {appendix.content}
          </pre>
        ) : (
          <div className="flex items-center justify-center h-full text-[13px] text-text-tertiary">
            Empty file
          </div>
        )}
      </div>
    </div>
  );
};
