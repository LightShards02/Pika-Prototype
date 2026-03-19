import { SettingsSection } from './SettingsSection';
import { SettingsField } from './SettingsField';

function getNestedValue(obj: Record<string, unknown>, path: string): unknown {
  const keys = path.split('.');
  let current: unknown = obj;
  for (const key of keys) {
    if (current == null || typeof current !== 'object') return undefined;
    current = (current as Record<string, unknown>)[key];
  }
  return current;
}

interface SettingsFormProps {
  data: Record<string, unknown>;
  onChange: (path: string, value: unknown) => void;
}

export const SettingsForm = ({ data, onChange }: SettingsFormProps) => {
  const str = (path: string) => (getNestedValue(data, path) as string) ?? '';
  const num = (path: string) => (getNestedValue(data, path) as number) ?? 0;
  const bool = (path: string) => (getNestedValue(data, path) as boolean) ?? false;

  const inputClass = 'w-full px-3 py-2 bg-bg-panel border border-border-medium rounded-md text-[13px] font-mono focus:outline-none focus:ring-1 focus:ring-accent-primary focus:border-accent-primary transition-all';
  const selectClass = 'px-3 py-2 bg-bg-panel border border-border-medium rounded-md text-[13px] focus:outline-none focus:ring-1 focus:ring-accent-primary focus:border-accent-primary transition-all';

  return (
    <div className="space-y-4">
      {/* Project */}
      <SettingsSection title="Project" defaultExpanded>
        <SettingsField label="Name" description="Project display name">
          <input className={inputClass} value={str('project.name')} onChange={(e) => onChange('project.name', e.target.value)} />
        </SettingsField>
        <SettingsField label="Root Directory" description="Absolute or relative project root">
          <input className={inputClass} value={str('project.root_dir')} onChange={(e) => onChange('project.root_dir', e.target.value)} />
        </SettingsField>
        <SettingsField label="Control Vocab Path" description="Per-project controlled vocabulary YAML (optional)">
          <input className={inputClass} value={str('project.control_vocab_path')} onChange={(e) => onChange('project.control_vocab_path', e.target.value)} placeholder="Optional" />
        </SettingsField>
        <SettingsField label="Design Spec Path" description="Canonical design spec location">
          <input className={inputClass} value={str('project.state.design_spec_path')} onChange={(e) => onChange('project.state.design_spec_path', e.target.value)} />
        </SettingsField>
        <SettingsField label="ID Registry Path" description="Path for id_registry.json">
          <input className={inputClass} value={str('project.state.id_registry_path')} onChange={(e) => onChange('project.state.id_registry_path', e.target.value)} />
        </SettingsField>
        <SettingsField label="SADS ID Mapping Path" description="Path for sads_id_mapping.json">
          <input className={inputClass} value={str('project.state.sads_id_mapping_path')} onChange={(e) => onChange('project.state.sads_id_mapping_path', e.target.value)} />
        </SettingsField>
      </SettingsSection>

      {/* Agent */}
      <SettingsSection title="Agent" defaultExpanded>
        <SettingsField label="Provider" description="Agent execution provider">
          <select className={selectClass} value={str('agent.provider')} onChange={(e) => onChange('agent.provider', e.target.value)}>
            <option value="stub">stub (mock)</option>
            <option value="api">api (remote HTTP)</option>
            <option value="local">local (CLI subprocess)</option>
          </select>
        </SettingsField>
        <SettingsField label="Schema Validation Retries" description="Retries when agent output fails schema validation">
          <input type="number" min={0} className={inputClass} value={num('agent.schema_validation_retries')} onChange={(e) => onChange('agent.schema_validation_retries', parseInt(e.target.value) || 0)} />
        </SettingsField>
        <SettingsField label="Stream Output" description="Stream agent output to terminal">
          <label className="flex items-center gap-2 cursor-pointer">
            <input type="checkbox" className="w-4 h-4 text-accent-primary rounded" checked={bool('agent.stream_output')} onChange={(e) => onChange('agent.stream_output', e.target.checked)} />
            <span className="text-[13px] text-text-secondary">Enabled</span>
          </label>
        </SettingsField>

        {str('agent.provider') === 'api' && (
          <>
            <SettingsField label="API Key Env" description="Environment variable for API Bearer token">
              <input className={inputClass} value={str('agent.api_key_env')} onChange={(e) => onChange('agent.api_key_env', e.target.value)} />
            </SettingsField>
            <SettingsField label="API URL" description="Chat completions API URL">
              <input className={inputClass} value={str('agent.api_url')} onChange={(e) => onChange('agent.api_url', e.target.value)} />
            </SettingsField>
            <SettingsField label="API Model" description="Model ID for API provider">
              <input className={inputClass} value={str('agent.api_model')} onChange={(e) => onChange('agent.api_model', e.target.value)} />
            </SettingsField>
          </>
        )}

        {str('agent.provider') === 'local' && (
          <>
            <SettingsField label="Local Command" description="Executable name or path (default: codex)">
              <input className={inputClass} value={str('agent.local_command')} onChange={(e) => onChange('agent.local_command', e.target.value)} placeholder="codex" />
            </SettingsField>
            <SettingsField label="Local Exec Timeout" description="Timeout in seconds for local subprocess">
              <input type="number" min={1} className={inputClass} value={num('agent.local_exec_timeout_sec')} onChange={(e) => onChange('agent.local_exec_timeout_sec', parseInt(e.target.value) || 60)} />
            </SettingsField>
          </>
        )}
      </SettingsSection>

      {/* Commands */}
      <SettingsSection title="Commands">
        <p className="text-[12px] text-text-tertiary mb-3">
          Toggle commands and set prompt names. Use Raw YAML mode for advanced command settings.
        </p>
        {(['format', 'map', 'review', 'refine', 'implement', 'resolve_plan', 'plan'] as const).map((cmd) => {
          const enabled = bool(`commands.${cmd}.enabled`);
          const promptPath = cmd === 'resolve_plan'
            ? `commands.${cmd}.map_prompt_name`
            : `commands.${cmd}.prompt_name`;
          const promptValue = str(promptPath);

          return (
            <div key={cmd} className="flex items-center gap-4 py-2 border-b border-border-subtle last:border-b-0">
              <label className="flex items-center gap-2 w-40 cursor-pointer">
                <input
                  type="checkbox"
                  className="w-4 h-4 text-accent-primary rounded"
                  checked={enabled}
                  onChange={(e) => onChange(`commands.${cmd}.enabled`, e.target.checked)}
                />
                <span className="text-[13px] font-medium text-text-primary">{cmd}</span>
              </label>
              {cmd !== 'format' && (
                <input
                  className={inputClass}
                  value={promptValue}
                  onChange={(e) => onChange(promptPath, e.target.value)}
                  placeholder="prompt_name"
                />
              )}
            </div>
          );
        })}
      </SettingsSection>

      {/* Logging */}
      <SettingsSection title="Logging">
        <SettingsField label="Level" description="Log level for console output">
          <select className={selectClass} value={str('logging.level')} onChange={(e) => onChange('logging.level', e.target.value)}>
            {['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'].map((lvl) => (
              <option key={lvl} value={lvl}>{lvl}</option>
            ))}
          </select>
        </SettingsField>
        <SettingsField label="Verbose Level" description="Log level for verbose mode">
          <select className={selectClass} value={str('logging.verbose_level')} onChange={(e) => onChange('logging.verbose_level', e.target.value)}>
            {['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'].map((lvl) => (
              <option key={lvl} value={lvl}>{lvl}</option>
            ))}
          </select>
        </SettingsField>
        <SettingsField label="JSON Logging" description="Output logs as JSON">
          <label className="flex items-center gap-2 cursor-pointer">
            <input type="checkbox" className="w-4 h-4 text-accent-primary rounded" checked={bool('logging.json')} onChange={(e) => onChange('logging.json', e.target.checked)} />
            <span className="text-[13px] text-text-secondary">Enabled</span>
          </label>
        </SettingsField>
        <SettingsField label="Log Directory" description="Directory for log files">
          <input className={inputClass} value={str('logging.log_dir')} onChange={(e) => onChange('logging.log_dir', e.target.value)} />
        </SettingsField>
      </SettingsSection>

      {/* Prompts & Schemas */}
      <SettingsSection title="Prompts & Schemas">
        <SettingsField label="Prompt File" description="Path to the prompt definitions file">
          <input className={inputClass} value={str('prompts.prompt_file')} onChange={(e) => onChange('prompts.prompt_file', e.target.value)} />
        </SettingsField>
        <SettingsField label="Map Output Schema" description="JSON Schema for map output">
          <input className={inputClass} value={str('schemas.map_output')} onChange={(e) => onChange('schemas.map_output', e.target.value)} />
        </SettingsField>
        <SettingsField label="Implement Output Schema" description="JSON Schema for implement output">
          <input className={inputClass} value={str('schemas.implement_output')} onChange={(e) => onChange('schemas.implement_output', e.target.value)} />
        </SettingsField>
        <SettingsField label="Resolve Plan Map Schema" description="JSON Schema for resolve plan map output">
          <input className={inputClass} value={str('schemas.resolve_plan_map_output')} onChange={(e) => onChange('schemas.resolve_plan_map_output', e.target.value)} />
        </SettingsField>
        <SettingsField label="Resolve Plan Output Schema" description="JSON Schema for resolve plan output">
          <input className={inputClass} value={str('schemas.resolve_plan_output')} onChange={(e) => onChange('schemas.resolve_plan_output', e.target.value)} />
        </SettingsField>
      </SettingsSection>

      {/* Codebase Transmission */}
      <SettingsSection title="Codebase Transmission">
        <p className="text-[12px] text-text-tertiary mb-3">
          Controls how source files are included in prompts for API-based agents. Ignored when provider is local.
        </p>
        <SettingsField label="Max Summary Chars" description="Cap on total snapshot size (default: 200000)">
          <input type="number" min={1000} className={inputClass} value={num('codebase_transmission.max_summary_chars')} onChange={(e) => onChange('codebase_transmission.max_summary_chars', parseInt(e.target.value) || 200000)} />
        </SettingsField>
        <SettingsField label="Max Raw Files" description="Raw files to include (default: 10)">
          <input type="number" min={1} className={inputClass} value={num('codebase_transmission.max_raw_files')} onChange={(e) => onChange('codebase_transmission.max_raw_files', parseInt(e.target.value) || 10)} />
        </SettingsField>
        <SettingsField label="Max Raw Chars Per File" description="Truncate raw files longer than this (default: 5000)">
          <input type="number" min={100} className={inputClass} value={num('codebase_transmission.max_raw_chars_per_file')} onChange={(e) => onChange('codebase_transmission.max_raw_chars_per_file', parseInt(e.target.value) || 5000)} />
        </SettingsField>
        <SettingsField label="Depth Limit" description="Max directory depth from codebase root (default: 15)">
          <input type="number" min={1} className={inputClass} value={num('codebase_transmission.depth_limit')} onChange={(e) => onChange('codebase_transmission.depth_limit', parseInt(e.target.value) || 15)} />
        </SettingsField>
      </SettingsSection>

      {/* ID Generation (read-only) */}
      <SettingsSection title="ID Generation">
        <p className="text-[12px] text-text-tertiary mb-3">
          ID patterns are locked. Use Raw YAML mode to view the full configuration.
        </p>
        <SettingsField label="Spec Pattern">
          <input className={inputClass + ' bg-bg-elevated text-text-tertiary'} value={str('id_generation.spec.pattern')} readOnly />
        </SettingsField>
        <SettingsField label="Issue Pattern">
          <input className={inputClass + ' bg-bg-elevated text-text-tertiary'} value={str('id_generation.issue.pattern')} readOnly />
        </SettingsField>
        <SettingsField label="Collision Scope">
          <input className={inputClass + ' bg-bg-elevated text-text-tertiary'} value={str('id_generation.collision_scope')} readOnly />
        </SettingsField>
      </SettingsSection>
    </div>
  );
};
