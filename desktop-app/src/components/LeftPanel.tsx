import { FileCode, FileText, Table2 } from 'lucide-react';
import { clsx } from 'clsx';
import { useStore } from '../store';
import { SpecViewer } from './SpecViewer';
import { AppendixViewer } from './AppendixViewer';

export const LeftPanel = () => {
  const { appendixes, activeLeftTab, setActiveLeftTab } = useStore();

  // No appendixes — render SpecViewer directly without tab bar
  if (appendixes.length === 0) {
    return <SpecViewer />;
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Tab bar */}
      <div className="flex items-center gap-1 px-3 py-2 border-b border-border-subtle bg-bg-primary overflow-x-auto shrink-0">
        <TabButton
          active={activeLeftTab === 'spec'}
          onClick={() => setActiveLeftTab('spec')}
          icon={<FileCode size={14} />}
          label="Design Spec"
        />
        {appendixes.map((a) => (
          <TabButton
            key={a.id}
            active={activeLeftTab === a.id}
            onClick={() => setActiveLeftTab(a.id)}
            icon={a.type === 'table' ? <Table2 size={14} /> : <FileText size={14} />}
            label={a.fileName}
          />
        ))}
      </div>

      {/* Content area */}
      <div className="flex-1 overflow-hidden">
        {activeLeftTab === 'spec' ? (
          <SpecViewer />
        ) : (
          <AppendixViewer appendixId={activeLeftTab} />
        )}
      </div>
    </div>
  );
};

const TabButton = ({
  active,
  onClick,
  icon,
  label,
}: {
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  label: string;
}) => (
  <button
    onClick={onClick}
    className={clsx(
      'flex items-center gap-1.5 px-3 py-1.5 text-[12px] font-medium rounded-md whitespace-nowrap transition-colors cursor-pointer',
      active
        ? 'bg-white shadow-sm text-text-primary'
        : 'text-text-tertiary hover:text-text-secondary hover:bg-bg-elevated'
    )}
    title={label}
  >
    {icon}
    <span className="max-w-[120px] truncate">{label}</span>
  </button>
);
