import { useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
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

const COMMANDS = [
  { key: 'format', label: 'Format' },
  { key: 'map', label: 'Map' },
  { key: 'implement', label: 'Implement' },
  { key: 'refine', label: 'Refine' },
  { key: 'resolve_plan', label: 'Resolve Plan' },
  { key: 'plan', label: 'Plan' },
  { key: 'review', label: 'Review' },
] as const;

export const SettingsForm = ({ data, onChange }: SettingsFormProps) => {
  const [expandedCmds, setExpandedCmds] = useState<Set<string>>(new Set());

  const str = (path: string) => (getNestedValue(data, path) as string) ?? '';
  const num = (path: string) => (getNestedValue(data, path) as number) ?? 0;
  const bool = (path: string) => (getNestedValue(data, path) as boolean) ?? false;

  const toggleCmd = (cmd: string) => {
    setExpandedCmds((prev) => {
      const next = new Set(prev);
      if (next.has(cmd)) next.delete(cmd);
      else next.add(cmd);
      return next;
    });
  };

  const inputClass =
    'w-full px-3 py-2 bg-bg-panel border border-border-medium rounded-md text-[13px] font-mono focus:outline-none focus:ring-1 focus:ring-accent-primary focus:border-accent-primary transition-all';
  const selectClass =
    'px-3 py-2 bg-bg-panel border border-border-medium rounded-md text-[13px] focus:outline-none focus:ring-1 focus:ring-accent-primary focus:border-accent-primary transition-all';
  const compactLabelClass = 'text-[11px] text-text-tertiary mb-1 block';

  const renderCommandDetails = (cmd: string) => {
    switch (cmd) {
      case 'format':
        return (
          <SettingsField label="Input Design Spec" description="Source CSV path for format command">
            <input
              className={inputClass}
              value={str('commands.format.inputs.design_spec_path')}
              onChange={(e) => onChange('commands.format.inputs.design_spec_path', e.target.value)}
              placeholder="raw-design-spec.csv"
            />
          </SettingsField>
        );

      case 'map':
        return (
          <>
            <SettingsField label="Skip Mapped" description="Skip map_status=mapped rows on re-runs">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  className="w-4 h-4 text-accent-primary rounded"
                  checked={bool('commands.map.skip_mapped')}
                  onChange={(e) => onChange('commands.map.skip_mapped', e.target.checked)}
                />
                <span className="text-[13px] text-text-secondary">Enabled</span>
              </label>
            </SettingsField>
            <SettingsField label="Max Acceptance Chars" description="Truncate acceptance_criteria (0 = unlimited)">
              <input
                type="number"
                min={0}
                className={inputClass}
                value={num('commands.map.max_acceptance_chars')}
                onChange={(e) => onChange('commands.map.max_acceptance_chars', parseInt(e.target.value) || 0)}
              />
            </SettingsField>
            <SettingsField label="Max Specs Per Subunit" description="Split subunits larger than this into sub-batches">
              <input
                type="number"
                min={1}
                className={inputClass}
                value={num('commands.map.max_specs_per_subunit') || ''}
                onChange={(e) => {
                  const v = parseInt(e.target.value);
                  onChange('commands.map.max_specs_per_subunit', v > 0 ? v : undefined);
                }}
                placeholder="Optional"
              />
            </SettingsField>
            <SettingsField
              label="Min Remap Confidence"
              description="Re-map 'mapped' rows below this threshold (0 = disabled)"
            >
              <input
                type="number"
                min={0}
                max={1}
                step={0.05}
                className={inputClass}
                value={num('commands.map.min_remapping_confidence_threshold') || ''}
                onChange={(e) => {
                  const v = parseFloat(e.target.value);
                  onChange('commands.map.min_remapping_confidence_threshold', isNaN(v) ? undefined : v);
                }}
                placeholder="0.0"
              />
            </SettingsField>
            <SettingsField
              label="Max Problem Threshold"
              description="Populate problems when confidence < threshold (default 1.0)"
            >
              <input
                type="number"
                min={0}
                max={1}
                step={0.05}
                className={inputClass}
                value={num('commands.map.max_problem_threshold') || ''}
                onChange={(e) => {
                  const v = parseFloat(e.target.value);
                  onChange('commands.map.max_problem_threshold', isNaN(v) ? undefined : v);
                }}
                placeholder="1.0"
              />
            </SettingsField>
          </>
        );

      case 'implement':
        return (
          <>
            <SettingsField label="Issue Tracker Path" description="CSV path for verification failures">
              <input
                className={inputClass}
                value={str('commands.implement.issue_tracker_path')}
                onChange={(e) => onChange('commands.implement.issue_tracker_path', e.target.value)}
                placeholder="out/issue_tracking.csv"
              />
            </SettingsField>
            <SettingsField label="Test Spec Path" description="Test spec CSV generated by implement">
              <input
                className={inputClass}
                value={str('commands.implement.test_spec_path')}
                onChange={(e) => onChange('commands.implement.test_spec_path', e.target.value)}
                placeholder="out/state/test_spec.csv"
              />
            </SettingsField>
            <SettingsField label="Type Placement Path" description="Path prefix for cross-module shared types">
              <input
                className={inputClass}
                value={str('commands.implement.type_placement_path')}
                onChange={(e) => onChange('commands.implement.type_placement_path', e.target.value)}
                placeholder="workspace/shared-contracts/"
              />
            </SettingsField>
            <SettingsField label="Min Confidence" description="Items below this block until resolved (0 = disabled)">
              <input
                type="number"
                min={0}
                max={1}
                step={0.05}
                className={inputClass}
                value={num('commands.implement.min_confidence_threshold') || ''}
                onChange={(e) => {
                  const v = parseFloat(e.target.value);
                  onChange('commands.implement.min_confidence_threshold', isNaN(v) ? undefined : v);
                }}
                placeholder="0.7"
              />
            </SettingsField>
            <div className="pt-1">
              <div className="text-[12px] font-medium text-text-secondary mb-2">Budgets</div>
              <div className="grid grid-cols-2 gap-x-4 gap-y-3">
                <div>
                  <label className={compactLabelClass}>Max Specs / Batch</label>
                  <input
                    type="number"
                    min={1}
                    className={inputClass}
                    value={num('commands.implement.budgets.max_specs_per_batch') || ''}
                    onChange={(e) =>
                      onChange('commands.implement.budgets.max_specs_per_batch', parseInt(e.target.value) || undefined)
                    }
                    placeholder="15"
                  />
                </div>
                <div>
                  <label className={compactLabelClass}>Max Files</label>
                  <input
                    type="number"
                    min={1}
                    className={inputClass}
                    value={num('commands.implement.budgets.max_files') || ''}
                    onChange={(e) =>
                      onChange('commands.implement.budgets.max_files', parseInt(e.target.value) || undefined)
                    }
                    placeholder="10"
                  />
                </div>
                <div>
                  <label className={compactLabelClass}>Max Lines Changed</label>
                  <input
                    type="number"
                    min={1}
                    className={inputClass}
                    value={num('commands.implement.budgets.max_lines_changed') || ''}
                    onChange={(e) =>
                      onChange('commands.implement.budgets.max_lines_changed', parseInt(e.target.value) || undefined)
                    }
                    placeholder="600"
                  />
                </div>
                <div>
                  <label className={compactLabelClass}>Max Context Tokens</label>
                  <input
                    type="number"
                    min={1}
                    className={inputClass}
                    value={num('commands.implement.budgets.max_context_tokens') || ''}
                    onChange={(e) =>
                      onChange('commands.implement.budgets.max_context_tokens', parseInt(e.target.value) || undefined)
                    }
                    placeholder="12000"
                  />
                </div>
              </div>
            </div>
            <p className="text-[11px] text-text-tertiary mt-2">
              Step toggles, unified planner, and module role settings are available in Raw YAML mode.
            </p>
          </>
        );

      case 'refine':
        return (
          <>
            <div>
              <div className="text-[12px] font-medium text-text-secondary mb-2">Decomposition</div>
              <div className="space-y-3 pl-3 border-l-2 border-border-subtle">
                <div className="flex items-center gap-6">
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      className="w-4 h-4 text-accent-primary rounded"
                      checked={bool('commands.refine.decomposition.enabled')}
                      onChange={(e) => onChange('commands.refine.decomposition.enabled', e.target.checked)}
                    />
                    <span className="text-[13px] text-text-secondary">Enabled</span>
                  </label>
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      className="w-4 h-4 text-accent-primary rounded"
                      checked={bool('commands.refine.decomposition.blocking')}
                      onChange={(e) => onChange('commands.refine.decomposition.blocking', e.target.checked)}
                    />
                    <span className="text-[13px] text-text-secondary">Blocking</span>
                  </label>
                </div>
                <div className="grid grid-cols-2 gap-x-4 gap-y-3">
                  <div>
                    <label className={compactLabelClass}>Similarity Threshold (0–1)</label>
                    <input
                      type="number"
                      min={0}
                      max={1}
                      step={0.05}
                      className={inputClass}
                      value={num('commands.refine.decomposition.similarity_threshold')}
                      onChange={(e) =>
                        onChange(
                          'commands.refine.decomposition.similarity_threshold',
                          parseFloat(e.target.value) || 0,
                        )
                      }
                    />
                  </div>
                  <div>
                    <label className={compactLabelClass}>Variance Threshold</label>
                    <input
                      type="number"
                      min={0}
                      step={0.05}
                      className={inputClass}
                      value={num('commands.refine.decomposition.variance_threshold')}
                      onChange={(e) =>
                        onChange('commands.refine.decomposition.variance_threshold', parseFloat(e.target.value) || 0)
                      }
                    />
                  </div>
                </div>
              </div>
            </div>
            <SettingsField label="Design Spec Path" description="Input design spec for refine">
              <input
                className={inputClass}
                value={str('commands.refine.inputs.design_spec_path')}
                onChange={(e) => onChange('commands.refine.inputs.design_spec_path', e.target.value)}
              />
            </SettingsField>
            <SettingsField label="Project Context" description="Project context filename">
              <input
                className={inputClass}
                value={str('commands.refine.inputs.project_context_filename')}
                onChange={(e) => onChange('commands.refine.inputs.project_context_filename', e.target.value)}
                placeholder="PROJECT_CONTEXT.md"
              />
            </SettingsField>
          </>
        );

      case 'resolve_plan':
        return (
          <>
            <SettingsField label="Design Spec Path" description="Input design spec">
              <input
                className={inputClass}
                value={str('commands.resolve_plan.inputs.design_spec_path')}
                onChange={(e) => onChange('commands.resolve_plan.inputs.design_spec_path', e.target.value)}
              />
            </SettingsField>
            <SettingsField label="Issue Tracking Path" description="Issue tracking CSV">
              <input
                className={inputClass}
                value={str('commands.resolve_plan.inputs.issue_tracking_path')}
                onChange={(e) => onChange('commands.resolve_plan.inputs.issue_tracking_path', e.target.value)}
              />
            </SettingsField>
          </>
        );

      case 'plan':
        return (
          <>
            <SettingsField label="SRS Path" description="Software requirements specification">
              <input
                className={inputClass}
                value={str('commands.plan.inputs.srs_path')}
                onChange={(e) => onChange('commands.plan.inputs.srs_path', e.target.value)}
                placeholder="specs/srs.md"
              />
            </SettingsField>
            <SettingsField label="Project Context" description="Project context filename">
              <input
                className={inputClass}
                value={str('commands.plan.inputs.project_context_filename')}
                onChange={(e) => onChange('commands.plan.inputs.project_context_filename', e.target.value)}
                placeholder="PROJECT_CONTEXT.md"
              />
            </SettingsField>
          </>
        );

      case 'review':
        return (
          <>
            <SettingsField label="SRS Path" description="Software requirements specification">
              <input
                className={inputClass}
                value={str('commands.review.inputs.srs_path')}
                onChange={(e) => onChange('commands.review.inputs.srs_path', e.target.value)}
                placeholder="specs/srs.md"
              />
            </SettingsField>
            <SettingsField label="Design Spec Path" description="Input design spec">
              <input
                className={inputClass}
                value={str('commands.review.inputs.design_spec_path')}
                onChange={(e) => onChange('commands.review.inputs.design_spec_path', e.target.value)}
              />
            </SettingsField>
            <SettingsField label="Project Context" description="Project context filename">
              <input
                className={inputClass}
                value={str('commands.review.inputs.project_context_filename')}
                onChange={(e) => onChange('commands.review.inputs.project_context_filename', e.target.value)}
                placeholder="PROJECT_CONTEXT.md"
              />
            </SettingsField>
          </>
        );

      default:
        return null;
    }
  };

  return (
    <div className="space-y-4">
      {/* ── Project ─────────────────────────────────────────── */}
      <SettingsSection title="Project" defaultExpanded>
        <SettingsField label="Name" description="Project display name">
          <input
            className={inputClass}
            value={str('project.name')}
            onChange={(e) => onChange('project.name', e.target.value)}
          />
        </SettingsField>
        <SettingsField label="Root Directory" description="Absolute or relative project root">
          <input
            className={inputClass}
            value={str('project.root_dir')}
            onChange={(e) => onChange('project.root_dir', e.target.value)}
          />
        </SettingsField>
        <SettingsField label="Control Vocab Path" description="Per-project controlled vocabulary YAML (optional)">
          <input
            className={inputClass}
            value={str('project.control_vocab_path')}
            onChange={(e) => onChange('project.control_vocab_path', e.target.value)}
            placeholder="Optional"
          />
        </SettingsField>
        <SettingsField label="Design Spec Path" description="Canonical design spec location">
          <input
            className={inputClass}
            value={str('project.state.design_spec_path')}
            onChange={(e) => onChange('project.state.design_spec_path', e.target.value)}
          />
        </SettingsField>
        <SettingsField label="ID Registry Path" description="Path for id_registry.json">
          <input
            className={inputClass}
            value={str('project.state.id_registry_path')}
            onChange={(e) => onChange('project.state.id_registry_path', e.target.value)}
          />
        </SettingsField>
        <SettingsField label="SADS ID Mapping Path" description="Path for sads_id_mapping.json">
          <input
            className={inputClass}
            value={str('project.state.sads_id_mapping_path')}
            onChange={(e) => onChange('project.state.sads_id_mapping_path', e.target.value)}
          />
        </SettingsField>
      </SettingsSection>

      {/* ── Agent ───────────────────────────────────────────── */}
      <SettingsSection title="Agent" defaultExpanded>
        <SettingsField label="Provider" description="Agent execution provider">
          <select
            className={selectClass}
            value={str('agent.provider')}
            onChange={(e) => onChange('agent.provider', e.target.value)}
          >
            <option value="stub">stub (mock)</option>
            <option value="api">api (remote HTTP)</option>
            <option value="local">local (CLI subprocess)</option>
          </select>
        </SettingsField>
        <SettingsField label="Schema Validation Retries" description="Retries when agent output fails schema validation">
          <input
            type="number"
            min={0}
            className={inputClass}
            value={num('agent.schema_validation_retries')}
            onChange={(e) => onChange('agent.schema_validation_retries', parseInt(e.target.value) || 0)}
          />
        </SettingsField>
        <SettingsField label="Stream Output" description="Stream agent output to terminal">
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              className="w-4 h-4 text-accent-primary rounded"
              checked={bool('agent.stream_output')}
              onChange={(e) => onChange('agent.stream_output', e.target.checked)}
            />
            <span className="text-[13px] text-text-secondary">Enabled</span>
          </label>
        </SettingsField>

        {str('agent.provider') === 'api' && (
          <>
            <SettingsField label="API Key Env" description="Environment variable for API Bearer token">
              <input
                className={inputClass}
                value={str('agent.api_key_env')}
                onChange={(e) => onChange('agent.api_key_env', e.target.value)}
              />
            </SettingsField>
            <SettingsField label="API URL" description="Chat completions API URL">
              <input
                className={inputClass}
                value={str('agent.api_url')}
                onChange={(e) => onChange('agent.api_url', e.target.value)}
              />
            </SettingsField>
            <SettingsField label="API Model" description="Model ID for API provider">
              <input
                className={inputClass}
                value={str('agent.api_model')}
                onChange={(e) => onChange('agent.api_model', e.target.value)}
              />
            </SettingsField>
          </>
        )}

        {str('agent.provider') === 'local' && (
          <>
            <SettingsField label="Local Command" description="Executable name or path (default: codex)">
              <input
                className={inputClass}
                value={str('agent.local_command')}
                onChange={(e) => onChange('agent.local_command', e.target.value)}
                placeholder="codex"
              />
            </SettingsField>
            <SettingsField label="Local Exec Timeout" description="Timeout in seconds for local subprocess">
              <input
                type="number"
                min={1}
                className={inputClass}
                value={num('agent.local_exec_timeout_sec')}
                onChange={(e) => onChange('agent.local_exec_timeout_sec', parseInt(e.target.value) || 60)}
              />
            </SettingsField>
          </>
        )}
      </SettingsSection>

      {/* ── Commands ────────────────────────────────────────── */}
      <SettingsSection title="Commands">
        <p className="text-[12px] text-text-tertiary mb-3">
          Toggle commands and configure settings. Output paths and step toggles are available in Raw YAML mode.
        </p>
        {COMMANDS.map(({ key, label }) => {
          const enabled = bool(`commands.${key}.enabled`);
          const isExpanded = expandedCmds.has(key);
          const details = renderCommandDetails(key);

          return (
            <div key={key} className="border border-border-subtle rounded-lg overflow-hidden mb-2 last:mb-0">
              {/* Command header row */}
              <div className="flex items-center gap-3 px-4 py-2.5 bg-bg-elevated">
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    className="w-4 h-4 text-accent-primary rounded"
                    checked={enabled}
                    onChange={(e) => onChange(`commands.${key}.enabled`, e.target.checked)}
                  />
                  <span className="text-[13px] font-medium text-text-primary">{label}</span>
                </label>
                {details && (
                  <button
                    onClick={() => toggleCmd(key)}
                    className="ml-auto p-1 hover:bg-bg-panel rounded transition-colors cursor-pointer"
                    title={isExpanded ? 'Collapse settings' : 'Expand settings'}
                  >
                    {isExpanded ? (
                      <ChevronDown size={14} className="text-text-tertiary" />
                    ) : (
                      <ChevronRight size={14} className="text-text-tertiary" />
                    )}
                  </button>
                )}
              </div>
              {/* Expanded command settings */}
              {details && isExpanded && (
                <div className="px-4 py-3 space-y-3 border-t border-border-subtle bg-white">{details}</div>
              )}
            </div>
          );
        })}
      </SettingsSection>

      {/* ── ID Generation ──────────────────────────────────── */}
      <SettingsSection title="ID Generation">
        <SettingsField label="Registry Path" description="Path for id_registry.json output">
          <input
            className={inputClass}
            value={str('id_generation.registry_path')}
            onChange={(e) => onChange('id_generation.registry_path', e.target.value)}
          />
        </SettingsField>
      </SettingsSection>

      {/* ── Logging ─────────────────────────────────────────── */}
      <SettingsSection title="Logging">
        <SettingsField label="Level" description="Log level for console output">
          <select
            className={selectClass}
            value={str('logging.level')}
            onChange={(e) => onChange('logging.level', e.target.value)}
          >
            {['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'].map((lvl) => (
              <option key={lvl} value={lvl}>
                {lvl}
              </option>
            ))}
          </select>
        </SettingsField>
        <SettingsField label="Verbose Level" description="Log level for verbose mode">
          <select
            className={selectClass}
            value={str('logging.verbose_level')}
            onChange={(e) => onChange('logging.verbose_level', e.target.value)}
          >
            {['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'].map((lvl) => (
              <option key={lvl} value={lvl}>
                {lvl}
              </option>
            ))}
          </select>
        </SettingsField>
        <SettingsField label="JSON Logging" description="Output logs as JSON">
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              className="w-4 h-4 text-accent-primary rounded"
              checked={bool('logging.json')}
              onChange={(e) => onChange('logging.json', e.target.checked)}
            />
            <span className="text-[13px] text-text-secondary">Enabled</span>
          </label>
        </SettingsField>
        <SettingsField label="Log Directory" description="Directory for log files">
          <input
            className={inputClass}
            value={str('logging.log_dir')}
            onChange={(e) => onChange('logging.log_dir', e.target.value)}
          />
        </SettingsField>
      </SettingsSection>

      {/* ── Codebase Transmission ──────────────────────────── */}
      <SettingsSection title="Codebase Transmission">
        <p className="text-[12px] text-text-tertiary mb-3">
          Controls how source files are included in prompts for API-based agents. Ignored when provider is local.
        </p>
        <SettingsField label="Max Summary Chars" description="Cap on total snapshot size (default: 200000)">
          <input
            type="number"
            min={1000}
            className={inputClass}
            value={num('codebase_transmission.max_summary_chars') || ''}
            onChange={(e) =>
              onChange('codebase_transmission.max_summary_chars', parseInt(e.target.value) || undefined)
            }
            placeholder="200000"
          />
        </SettingsField>
        <SettingsField label="Max Raw Files" description="Raw files to include (default: 10)">
          <input
            type="number"
            min={1}
            className={inputClass}
            value={num('codebase_transmission.max_raw_files') || ''}
            onChange={(e) => onChange('codebase_transmission.max_raw_files', parseInt(e.target.value) || undefined)}
            placeholder="10"
          />
        </SettingsField>
        <SettingsField label="Max Raw Chars Per File" description="Truncate raw files longer than this (default: 5000)">
          <input
            type="number"
            min={100}
            className={inputClass}
            value={num('codebase_transmission.max_raw_chars_per_file') || ''}
            onChange={(e) =>
              onChange('codebase_transmission.max_raw_chars_per_file', parseInt(e.target.value) || undefined)
            }
            placeholder="5000"
          />
        </SettingsField>
        <SettingsField label="Depth Limit" description="Max directory depth from codebase root (default: 15)">
          <input
            type="number"
            min={1}
            className={inputClass}
            value={num('codebase_transmission.depth_limit') || ''}
            onChange={(e) => onChange('codebase_transmission.depth_limit', parseInt(e.target.value) || undefined)}
            placeholder="15"
          />
        </SettingsField>
      </SettingsSection>
    </div>
  );
};
