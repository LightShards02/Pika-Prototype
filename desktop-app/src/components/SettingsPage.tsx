import { useState, useEffect, useCallback } from 'react';
import { Save, FileText, FileCode, FolderOpen, FilePlus, Check, AlertCircle } from 'lucide-react';
import yaml from 'js-yaml';
import { clsx } from 'clsx';
import { useStore } from '../store';
import { TopBar } from './TopBar';
import { SettingsForm } from './settings/SettingsForm';
import { RawEditor } from './settings/RawEditor';
import { loadSchema, validateConfig, formatValidationErrors } from '../services/configValidator';
import type { ValidationError } from '../services/configValidator';

function setNestedValue(obj: Record<string, unknown>, path: string, value: unknown): Record<string, unknown> {
  const keys = path.split('.');
  const result = structuredClone(obj);
  let current: Record<string, unknown> = result;
  for (let i = 0; i < keys.length - 1; i++) {
    if (!current[keys[i]] || typeof current[keys[i]] !== 'object') {
      current[keys[i]] = {};
    }
    current = current[keys[i]] as Record<string, unknown>;
  }
  current[keys[keys.length - 1]] = value;
  return result;
}

export const SettingsPage = () => {
  const { configPath, setConfigPath } = useStore();

  const [configData, setConfigData] = useState<Record<string, unknown> | null>(null);
  const [rawYaml, setRawYaml] = useState('');
  const [mode, setMode] = useState<'form' | 'raw'>('form');
  const [isDirty, setIsDirty] = useState(false);
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');
  const [loadError, setLoadError] = useState<string | null>(null);
  const [parseError, setParseError] = useState<string | null>(null);
  const [validationErrors, setValidationErrors] = useState<ValidationError[]>([]);

  // Load JSON schema on mount (best-effort)
  useEffect(() => {
    loadSchema().catch(() => {
      // Schema loading is best-effort; validation skipped if unavailable
    });
  }, []);

  const loadConfig = useCallback(async () => {
    if (!configPath) {
      setConfigData(null);
      setRawYaml('');
      setLoadError(null);
      return;
    }
    try {
      const content = await window.electronAPI.readFile(configPath);
      const parsed = yaml.load(content) as Record<string, unknown>;
      setConfigData(parsed);
      setRawYaml(content);
      setIsDirty(false);
      setLoadError(null);
      setValidationErrors([]);
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : String(err));
      setConfigData(null);
      setRawYaml('');
    }
  }, [configPath]);

  useEffect(() => {
    loadConfig();
  }, [loadConfig]);

  const handleSave = async () => {
    if (!configPath) return;

    // Resolve data to validate
    let dataToValidate = configData;
    if (mode === 'raw') {
      try {
        dataToValidate = yaml.load(rawYaml) as Record<string, unknown>;
      } catch {
        setParseError('Invalid YAML — cannot validate or save');
        return;
      }
    }

    // Validate against JSON schema
    if (dataToValidate) {
      const errors = validateConfig(dataToValidate);
      setValidationErrors(errors);
      if (errors.length > 0) return;
    }

    setSaveStatus('saving');
    try {
      let content: string;
      if (mode === 'raw') {
        content = rawYaml;
      } else {
        content = yaml.dump(configData, { lineWidth: -1, noRefs: true });
      }
      await window.electronAPI.writeFile(configPath, content);
      setSaveStatus('saved');
      setIsDirty(false);
      setTimeout(() => setSaveStatus('idle'), 2000);
    } catch {
      setSaveStatus('error');
      setTimeout(() => setSaveStatus('idle'), 3000);
    }
  };

  const switchToMode = (newMode: 'form' | 'raw') => {
    if (newMode === mode) return;
    setParseError(null);

    if (newMode === 'raw' && configData) {
      setRawYaml(yaml.dump(configData, { lineWidth: -1, noRefs: true }));
      setMode('raw');
    } else if (newMode === 'form') {
      try {
        const parsed = yaml.load(rawYaml) as Record<string, unknown>;
        setConfigData(parsed);
        setMode('form');
      } catch (err) {
        setParseError(err instanceof Error ? err.message : 'Invalid YAML');
      }
    }
  };

  const handleFormChange = (path: string, value: unknown) => {
    if (!configData) return;
    setConfigData(setNestedValue(configData, path, value));
    setIsDirty(true);
    setValidationErrors([]);
  };

  const handleRawChange = (value: string) => {
    setRawYaml(value);
    setIsDirty(true);
    setParseError(null);
    setValidationErrors([]);
  };

  const handleBrowseConfig = async () => {
    const path = await window.electronAPI.openFileDialog({
      filters: [
        { name: 'YAML Files', extensions: ['yaml', 'yml'] },
        { name: 'All Files', extensions: ['*'] },
      ],
    });
    if (path) setConfigPath(path);
  };

  const handleCreateFromTemplate = async () => {
    try {
      const pikaRoot = await window.electronAPI.getPikaRoot();
      const templateContent = await window.electronAPI.readFile(pikaRoot + '/config/config.example.yaml');
      const savePath = await window.electronAPI.saveFileDialog({
        filters: [{ name: 'YAML Files', extensions: ['yaml', 'yml'] }],
        defaultPath: 'config.yaml',
      });
      if (!savePath) return;
      await window.electronAPI.writeFile(savePath, templateContent);
      setConfigPath(savePath);
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : String(err));
    }
  };

  const displayPath = (path: string) => {
    const parts = path.replace(/\\/g, '/').split('/');
    return parts[parts.length - 1] || path;
  };

  return (
    <div className="flex flex-col h-screen bg-bg-primary select-none">
      <TopBar />

      {/* Settings Header */}
      <div className="px-8 py-5 border-b border-border-subtle bg-bg-panel shrink-0">
        <div className="max-w-4xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-4">
            <h1 className="text-[20px] font-bold text-text-primary">Settings</h1>
            {configPath && (
              <span className="text-[12px] font-mono text-text-tertiary bg-bg-elevated px-2 py-1 rounded" title={configPath}>
                {displayPath(configPath)}
                {isDirty && <span className="text-warning ml-1">*</span>}
              </span>
            )}
          </div>

          <div className="flex items-center gap-3">
            {/* Mode Toggle */}
            {configData && (
              <div className="flex bg-bg-elevated rounded-lg p-0.5">
                <button
                  onClick={() => switchToMode('form')}
                  className={clsx(
                    'flex items-center gap-1.5 px-4 py-1.5 rounded-md text-[13px] font-medium transition-all cursor-pointer',
                    mode === 'form'
                      ? 'bg-white shadow-sm text-text-primary'
                      : 'text-text-tertiary hover:text-text-secondary'
                  )}
                >
                  <FileText size={14} />
                  Form
                </button>
                <button
                  onClick={() => switchToMode('raw')}
                  className={clsx(
                    'flex items-center gap-1.5 px-4 py-1.5 rounded-md text-[13px] font-medium transition-all cursor-pointer',
                    mode === 'raw'
                      ? 'bg-white shadow-sm text-text-primary'
                      : 'text-text-tertiary hover:text-text-secondary'
                  )}
                >
                  <FileCode size={14} />
                  Raw YAML
                </button>
              </div>
            )}

            {/* Save Button */}
            {configPath && configData && (
              <button
                onClick={handleSave}
                disabled={!isDirty || saveStatus === 'saving'}
                className={clsx(
                  'flex items-center gap-2 px-4 py-2 rounded-md text-[13px] font-semibold transition-all cursor-pointer',
                  isDirty && saveStatus !== 'saving'
                    ? 'bg-accent-primary text-white hover:bg-accent-deep shadow-md'
                    : 'bg-border-medium text-text-tertiary cursor-not-allowed'
                )}
              >
                {saveStatus === 'saving' ? (
                  'Saving...'
                ) : saveStatus === 'saved' ? (
                  <><Check size={16} /> Saved</>
                ) : saveStatus === 'error' ? (
                  <><AlertCircle size={16} /> Error</>
                ) : (
                  <><Save size={16} /> Save</>
                )}
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Parse Error Banner */}
      {parseError && (
        <div className="px-8 py-3 bg-[#FEE2E2] border-b border-error">
          <div className="max-w-4xl mx-auto text-[13px] text-[#991B1B]">
            <span className="font-semibold">YAML Parse Error:</span> {parseError}
          </div>
        </div>
      )}

      {/* Validation Error Banner */}
      {validationErrors.length > 0 && (
        <div className="px-8 py-3 bg-[#FEF3CD] border-b border-warning">
          <div className="max-w-4xl mx-auto">
            <div className="text-[13px] font-semibold text-[#856404] mb-1">
              Validation Errors ({validationErrors.length})
            </div>
            <ul className="text-[12px] text-[#856404] space-y-0.5 max-h-32 overflow-y-auto">
              {formatValidationErrors(validationErrors).map((msg, i) => (
                <li key={i} className="font-mono">{msg}</li>
              ))}
            </ul>
          </div>
        </div>
      )}

      {/* Content */}
      <div className="flex-1 overflow-y-auto">
        {!configPath ? (
          // No config selected
          <div className="flex-1 flex flex-col items-center justify-center p-12 text-center h-full">
            <div className="p-4 bg-bg-elevated rounded-full mb-6">
              <FileText size={48} className="text-text-tertiary" />
            </div>
            <h2 className="text-[18px] font-semibold text-text-primary mb-2">No Configuration File</h2>
            <p className="text-[14px] text-text-secondary mb-8 max-w-md">
              Select an existing workspace config file or create one from the default template.
            </p>
            <div className="flex gap-4">
              <button
                onClick={handleBrowseConfig}
                className="flex items-center gap-2 px-6 py-3 border border-border-medium rounded-lg text-[14px] font-medium hover:bg-bg-elevated transition-colors cursor-pointer"
              >
                <FolderOpen size={18} />
                Browse...
              </button>
              <button
                onClick={handleCreateFromTemplate}
                className="flex items-center gap-2 px-6 py-3 bg-accent-primary text-white rounded-lg text-[14px] font-medium hover:bg-accent-deep transition-colors cursor-pointer shadow-md"
              >
                <FilePlus size={18} />
                Create from Template
              </button>
            </div>
          </div>
        ) : loadError ? (
          // Load error
          <div className="flex-1 flex flex-col items-center justify-center p-12 text-center h-full">
            <AlertCircle size={48} className="text-error mb-4" />
            <h2 className="text-[18px] font-semibold text-text-primary mb-2">Failed to Load Config</h2>
            <p className="text-[14px] text-text-secondary mb-6 max-w-md font-mono">{loadError}</p>
            <button
              onClick={handleBrowseConfig}
              className="flex items-center gap-2 px-6 py-3 border border-border-medium rounded-lg text-[14px] font-medium hover:bg-bg-elevated transition-colors cursor-pointer"
            >
              <FolderOpen size={18} />
              Choose Different File
            </button>
          </div>
        ) : configData && mode === 'form' ? (
          <div className="max-w-4xl mx-auto p-8">
            <SettingsForm data={configData} onChange={handleFormChange} />
          </div>
        ) : (
          <div className="h-full">
            <RawEditor value={rawYaml} onChange={handleRawChange} />
          </div>
        )}
      </div>
    </div>
  );
};
