import { Play, FileCode, FolderOpen, Settings2 } from 'lucide-react';
import { useStore } from '../store';
import { TopBar } from './TopBar';

export const EntryScreen = () => {
  const { setRun } = useStore();

  const handleStart = () => {
    setRun({ status: 'running', progress: 0, runId: '5' });
  };

  return (
    <div className="flex flex-col h-screen bg-bg-primary select-none">
      <TopBar />
      <div className="flex-1 flex flex-col items-center justify-center bg-bg-panel p-12 overflow-y-auto">
        <div className="max-w-2xl w-full space-y-12">
          <div className="text-center">
            <h1 className="text-[32px] font-bold text-text-primary mb-2">Design Improvement</h1>
            <p className="text-[16px] text-text-secondary">Refine and implement your design spec with AI precision</p>
          </div>

          <div className="bg-white rounded-xl border border-border-subtle shadow-sm overflow-hidden">
            <div className="p-8 space-y-8">
              <section className="space-y-4">
                <div className="flex items-center gap-2 text-[13px] font-semibold text-text-tertiary uppercase tracking-wider">
                  <FileCode size={16} />
                  Design Spec
                </div>
                <div className="flex gap-3">
                  <div className="flex-1 px-4 py-3 bg-bg-panel border border-border-medium rounded-lg text-[14px] text-text-primary font-mono truncate">
                    my-design-spec.csv
                  </div>
                  <button className="px-4 py-2 border border-border-medium rounded-lg text-[13px] font-medium hover:bg-bg-elevated transition-colors cursor-pointer">
                    Browse...
                  </button>
                </div>
              </section>

              <section className="space-y-4">
                <div className="flex items-center gap-2 text-[13px] font-semibold text-text-tertiary uppercase tracking-wider">
                  <FolderOpen size={16} />
                  Codebase Directory
                </div>
                <div className="flex gap-3">
                  <div className="flex-1 px-4 py-3 bg-bg-panel border border-border-medium rounded-lg text-[14px] text-text-primary font-mono truncate">
                    src/
                  </div>
                  <button className="px-4 py-2 border border-border-medium rounded-lg text-[13px] font-medium hover:bg-bg-elevated transition-colors cursor-pointer">
                    Browse...
                  </button>
                </div>
              </section>

              <section className="space-y-4">
                <div className="flex items-center gap-2 text-[13px] font-semibold text-text-tertiary uppercase tracking-wider">
                  <Settings2 size={16} />
                  Options
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <label className="flex items-center gap-3 p-4 bg-bg-panel border border-border-subtle rounded-lg cursor-pointer hover:border-accent-primary transition-all">
                    <input type="checkbox" className="w-4 h-4 text-accent-primary rounded" defaultChecked />
                    <span className="text-[14px] font-medium">Run Refine</span>
                  </label>
                  <label className="flex items-center gap-3 p-4 bg-bg-panel border border-border-subtle rounded-lg cursor-pointer hover:border-accent-primary transition-all">
                    <input type="checkbox" className="w-4 h-4 text-accent-primary rounded" defaultChecked />
                    <span className="text-[14px] font-medium">Run Implement</span>
                  </label>
                  <label className="flex items-center gap-3 p-4 bg-bg-panel border border-border-subtle rounded-lg cursor-pointer hover:border-accent-primary transition-all">
                    <input type="checkbox" className="w-4 h-4 text-accent-primary rounded" defaultChecked />
                    <span className="text-[14px] font-medium">Decomposition check</span>
                  </label>
                </div>
              </section>
            </div>

            <div className="p-8 bg-bg-panel border-t border-border-subtle flex justify-end">
              <button 
                onClick={handleStart}
                className="group flex items-center gap-3 px-8 py-4 bg-accent-primary text-white rounded-lg text-[15px] font-bold hover:bg-accent-deep transition-all shadow-lg hover:shadow-xl cursor-pointer"
              >
                Start Design Improvement
                <Play size={20} className="fill-current group-hover:translate-x-1 transition-transform" />
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
