import { useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';

interface SettingsSectionProps {
  title: string;
  defaultExpanded?: boolean;
  children: React.ReactNode;
}

export const SettingsSection = ({ title, defaultExpanded = false, children }: SettingsSectionProps) => {
  const [isExpanded, setIsExpanded] = useState(defaultExpanded);

  return (
    <div className="border border-border-subtle rounded-lg overflow-hidden">
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full flex items-center gap-2 px-5 py-3.5 bg-bg-elevated hover:bg-bg-panel transition-colors cursor-pointer text-left"
      >
        {isExpanded ? (
          <ChevronDown size={16} className="text-text-tertiary" />
        ) : (
          <ChevronRight size={16} className="text-text-tertiary" />
        )}
        <span className="text-[13px] font-semibold text-text-primary uppercase tracking-wider">
          {title}
        </span>
      </button>
      {isExpanded && (
        <div className="px-5 py-4 space-y-4 bg-white border-t border-border-subtle">
          {children}
        </div>
      )}
    </div>
  );
};
