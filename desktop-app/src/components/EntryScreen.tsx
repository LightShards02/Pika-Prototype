import { useState } from 'react';
import { Play, FileCode, FolderOpen, Settings2, Paperclip, Plus, X, FileText, Table2 } from 'lucide-react';
import Papa from 'papaparse';
import { useStore } from '../store';
import { TopBar } from './TopBar';
import type { Spec, Appendix } from '../types';

export const EntryScreen = () => {
  const {
    setRun, setSpecs, resetForNewRun,
    projectRootPath, setProjectRootPath,
    designSpecPath, setDesignSpecPath,
    refineEnabled, setRefineEnabled,
    implementEnabled, setImplementEnabled,
    decompositionEnabled, setDecompositionEnabled,
    appendixes, addAppendix, removeAppendix, updateAppendixModuleTag, clearAppendixes,
    availableModuleTags, setAvailableModuleTags,
  } = useStore();

  const [error, setError] = useState<string | null>(null);

  const handleBrowseProjectRoot = async () => {
    const path = await window.electronAPI.openDirDialog();
    if (path) setProjectRootPath(path);
  };

  const handleBrowseDesignSpec = async () => {
    const path = await window.electronAPI.openFileDialog({
      filters: [{ name: 'CSV Files', extensions: ['csv'] }, { name: 'All Files', extensions: ['*'] }],
    });
    if (!path) return;
    setDesignSpecPath(path);
    clearAppendixes();

    try {
      const csvContent = await window.electronAPI.readFile(path);
      const parsed = Papa.parse<Record<string, string>>(csvContent, {
        header: true,
        skipEmptyLines: true,
      });
      const tags = [...new Set(
        parsed.data
          .map((row) => row['module_tag'] ?? row['Module_Tag'] ?? '')
          .filter(Boolean)
      )].sort();
      setAvailableModuleTags(tags);
    } catch {
      setAvailableModuleTags([]);
    }
  };

  const handleAddAppendix = async () => {
    const path = await window.electronAPI.openFileDialog({
      // Single default filter so OS dialog shows .csv alongside text types (first filter is the default on Windows).
      filters: [
        { name: 'Text and CSV', extensions: ['txt', 'md', 'rst', 'log', 'csv'] },
        { name: 'All Files', extensions: ['*'] },
      ],
    });
    if (!path) return;

    try {
      const content = await window.electronAPI.readFile(path);
      const parts = path.replace(/\\/g, '/').split('/');
      const fileName = parts[parts.length - 1] || path;
      const ext = fileName.split('.').pop()?.toLowerCase() ?? '';
      const type = ext === 'csv' ? 'table' as const : 'text' as const;

      const appendix: Appendix = {
        id: crypto.randomUUID(),
        fileName,
        filePath: path,
        type,
        moduleTag: availableModuleTags[0] ?? '',
        content,
      };

      if (type === 'table') {
        const parsed = Papa.parse<Record<string, string>>(content, {
          header: true,
          skipEmptyLines: true,
        });
        appendix.columns = parsed.meta.fields ?? [];
        appendix.parsedRows = parsed.data;
      }

      addAppendix(appendix);
    } catch (err) {
      setError(`Failed to load appendix: ${err instanceof Error ? err.message : String(err)}`);
    }
  };

  const handleStart = async () => {
    setError(null);

    if (!projectRootPath) {
      setError('Please select a project root directory.');
      return;
    }
    if (!designSpecPath) {
      setError('Please select a design spec CSV file.');
      return;
    }

    try {
      resetForNewRun();

      // Parse CSV and load specs into store
      const csvContent = await window.electronAPI.readFile(designSpecPath);
      const parsed = Papa.parse<Record<string, string>>(csvContent, {
        header: true,
        skipEmptyLines: true,
      });

      const specs: Spec[] = parsed.data.map((row) => ({
        spec_id: row['spec_id'] ?? row['Spec_ID'] ?? '',
        module_tag: row['module_tag'] ?? row['Module_Tag'] ?? '',
        module_role: row['module_role'] ?? row['Module_Role'] ?? '',
        requirement: row['requirement'] ?? row['Requirement'] ?? '',
        acceptance_criteria: row['acceptance_criteria'] ?? row['Acceptance_Criteria'] ?? '',
      })).filter((s) => s.spec_id);

      setSpecs(specs);
      setRun({
        status: 'running',
        progress: 0,
        specPath: designSpecPath,
        projectRoot: projectRootPath,
      });
    } catch (err) {
      setError(`Failed to load design spec: ${err instanceof Error ? err.message : String(err)}`);
    }
  };

  const displayPath = (path: string | null, fallback: string) => {
    if (!path) return fallback;
    // Show just the filename or last path segment
    const parts = path.replace(/\\/g, '/').split('/');
    return parts[parts.length - 1] || path;
  };

  return (
    <div className="flex flex-col h-screen bg-bg-primary select-none">
      <TopBar />
      <div className="flex-1 bg-bg-panel p-12 overflow-y-auto">
        <div className="max-w-2xl w-full mx-auto my-auto space-y-12">
          <div className="text-center">
            <h1 className="text-[32px] font-bold text-text-primary mb-2">Design Improvement</h1>
            <p className="text-[16px] text-text-secondary">Refine and implement your design spec with AI precision</p>
          </div>

          {error && (
            <div className="p-4 bg-[#FEE2E2] border border-error rounded-lg text-[14px] text-[#991B1B]">
              {error}
            </div>
          )}

          <div className="bg-white rounded-xl border border-border-subtle shadow-sm overflow-hidden">
            <div className="p-8 space-y-8">
              <section className="space-y-4">
                <div className="flex items-center gap-2 text-[13px] font-semibold text-text-tertiary uppercase tracking-wider">
                  <FolderOpen size={16} />
                  Project Root
                </div>
                <div className="flex gap-3">
                  <div
                    className="flex-1 px-4 py-3 bg-bg-panel border border-border-medium rounded-lg text-[14px] text-text-primary font-mono truncate"
                    title={projectRootPath ?? undefined}
                  >
                    {projectRootPath ? displayPath(projectRootPath, 'No directory selected') : 'No directory selected'}
                  </div>
                  <button
                    onClick={handleBrowseProjectRoot}
                    className="px-4 py-2 border border-border-medium rounded-lg text-[13px] font-medium hover:bg-bg-elevated transition-colors cursor-pointer"
                  >
                    Browse...
                  </button>
                </div>
                {projectRootPath && (
                  <div className="text-[12px] text-text-tertiary font-mono truncate" title={projectRootPath}>
                    {projectRootPath}
                  </div>
                )}
              </section>

              <section className="space-y-4">
                <div className="flex items-center gap-2 text-[13px] font-semibold text-text-tertiary uppercase tracking-wider">
                  <FileCode size={16} />
                  Design Spec
                </div>
                <div className="flex gap-3">
                  <div
                    className="flex-1 px-4 py-3 bg-bg-panel border border-border-medium rounded-lg text-[14px] text-text-primary font-mono truncate"
                    title={designSpecPath ?? undefined}
                  >
                    {designSpecPath ? displayPath(designSpecPath, 'No file selected') : 'No file selected'}
                  </div>
                  <button
                    onClick={handleBrowseDesignSpec}
                    className="px-4 py-2 border border-border-medium rounded-lg text-[13px] font-medium hover:bg-bg-elevated transition-colors cursor-pointer"
                  >
                    Browse...
                  </button>
                </div>
                {designSpecPath && (
                  <div className="text-[12px] text-text-tertiary font-mono truncate" title={designSpecPath}>
                    {designSpecPath}
                  </div>
                )}
              </section>

              <section className={`space-y-4 transition-opacity ${designSpecPath ? '' : 'opacity-40 pointer-events-none'}`}>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2 text-[13px] font-semibold text-text-tertiary uppercase tracking-wider">
                    <Paperclip size={16} />
                    Appendixes
                  </div>
                  <button
                    onClick={handleAddAppendix}
                    className="flex items-center gap-1 px-3 py-1.5 text-[12px] font-medium text-accent-primary border border-accent-primary rounded-lg hover:bg-indigo-light transition-colors cursor-pointer"
                  >
                    <Plus size={14} />
                    Add
                  </button>
                </div>

                {appendixes.length === 0 ? (
                  <div className="px-4 py-6 bg-bg-panel border border-border-subtle rounded-lg text-center text-[13px] text-text-tertiary">
                    Import reference files (plain text or CSV) to attach as appendixes
                  </div>
                ) : (
                  <div className="space-y-2">
                    {appendixes.map((a) => (
                      <div
                        key={a.id}
                        className="flex items-center gap-3 px-4 py-3 bg-bg-panel border border-border-subtle rounded-lg"
                      >
                        {a.type === 'table' ? (
                          <Table2 size={16} className="text-text-tertiary shrink-0" />
                        ) : (
                          <FileText size={16} className="text-text-tertiary shrink-0" />
                        )}
                        <span className="text-[13px] text-text-primary font-mono truncate flex-1" title={a.filePath}>
                          {a.fileName}
                        </span>
                        <span className="px-2 py-0.5 text-[10px] font-bold uppercase bg-bg-elevated text-text-secondary rounded shrink-0">
                          {a.type}
                        </span>
                        <select
                          value={a.moduleTag}
                          onChange={(e) => updateAppendixModuleTag(a.id, e.target.value)}
                          className="px-2 py-1 text-[12px] bg-white border border-border-medium rounded-md focus:outline-none focus:ring-1 focus:ring-accent-primary"
                        >
                          {availableModuleTags.length === 0 && (
                            <option value="">No tags</option>
                          )}
                          {availableModuleTags.map((tag) => (
                            <option key={tag} value={tag}>{tag}</option>
                          ))}
                        </select>
                        <button
                          onClick={() => removeAppendix(a.id)}
                          className="p-1 text-text-tertiary hover:text-error rounded transition-colors cursor-pointer"
                        >
                          <X size={14} />
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </section>

              <section className="space-y-4">
                <div className="flex items-center gap-2 text-[13px] font-semibold text-text-tertiary uppercase tracking-wider">
                  <Settings2 size={16} />
                  Options
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <label className="flex items-center gap-3 p-4 bg-bg-panel border border-border-subtle rounded-lg cursor-pointer hover:border-accent-primary transition-all">
                    <input
                      type="checkbox"
                      className="w-4 h-4 text-accent-primary rounded"
                      checked={refineEnabled}
                      onChange={(e) => setRefineEnabled(e.target.checked)}
                    />
                    <span className="text-[14px] font-medium">Run Refine</span>
                  </label>
                  <label className="flex items-center gap-3 p-4 bg-bg-panel border border-border-subtle rounded-lg cursor-pointer hover:border-accent-primary transition-all">
                    <input
                      type="checkbox"
                      className="w-4 h-4 text-accent-primary rounded"
                      checked={implementEnabled}
                      onChange={(e) => setImplementEnabled(e.target.checked)}
                    />
                    <span className="text-[14px] font-medium">Run Implement</span>
                  </label>
                  <label className="flex items-center gap-3 p-4 bg-bg-panel border border-border-subtle rounded-lg cursor-pointer hover:border-accent-primary transition-all">
                    <input
                      type="checkbox"
                      className="w-4 h-4 text-accent-primary rounded"
                      checked={decompositionEnabled}
                      onChange={(e) => setDecompositionEnabled(e.target.checked)}
                    />
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
