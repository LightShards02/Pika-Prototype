export interface Spec {
  spec_id: string;
  module_tag: string;
  module_role: string;
  requirement: string;
  acceptance_criteria: string;
  status?: string;
}

export type PhaseStatus = 'pending' | 'running' | 'done' | 'failed' | 'blocked' | 'waiting';

export interface Phase {
  id: string;
  name: string;
  group: 'Refine' | 'Implement' | 'Batch';
  status: PhaseStatus;
  description: string;
  isBlocking: boolean;
  issuesCount?: number;
}

export interface ResolutionItem {
  id: string;
  spec_ids: string[];
  type: string;
  reason: string;
  currentText?: string;
  suggestedText?: string;
  options: ResolutionOption[];
  selectedOption?: string;
}

export interface ResolutionOption {
  id: string;
  label: string;
  description?: string;
}

export interface RunState {
  currentPhaseId: string;
  progress: number;
  status: 'idle' | 'running' | 'paused' | 'completed' | 'failed';
  runId?: string;
  specPath?: string;
  projectRoot?: string;
}
