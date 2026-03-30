import type { Spec, RawAmbiguityItem, RawTestabilityItem, ResolutionItem, Appendix, PikaPreferences } from '../../src/types';

export const mockSpecs: Spec[] = [
  {
    spec_id: 'SPEC-001',
    module_tag: 'AUTH',
    module_role: 'Authentication',
    requirement: 'System shall authenticate users via OAuth2',
    acceptance_criteria: 'User receives a valid JWT token',
  },
  {
    spec_id: 'SPEC-002',
    module_tag: 'EXPORT',
    module_role: 'Data Export',
    requirement: 'System shall export data to CSV',
    acceptance_criteria: 'Downloaded file contains all visible rows',
  },
];

export const mockAmbiguityItem: RawAmbiguityItem = {
  item_id: 'AMB-001',
  title: 'Vague authentication requirement',
  spec_id: 'SPEC-001',
  field: 'requirement',
  vague_phrases: ['authenticate users'],
  suggested_improvement: 'System shall authenticate users via OAuth2 with PKCE flow',
  options: [
    { option_id: 'accept_suggestion', label: 'Accept Suggestion', effect: 'Replace with suggested text' },
    { option_id: 'let_agent_edit', label: 'Let Agent Edit', effect: 'Agent will rewrite' },
    { option_id: 'skip', label: 'Skip', effect: 'Keep original' },
  ],
};

export const mockTestabilityItem: RawTestabilityItem = {
  item_id: 'TST-001',
  title: 'Untestable acceptance criteria',
  spec_id: 'SPEC-002',
  field: 'acceptance_criteria',
  untestable_reason: 'No measurable criterion for "all visible rows"',
  suggested_improvement: 'Downloaded CSV contains exactly N rows matching the current filter',
  suggested_test_type: 'integration',
  options: [
    { option_id: 'accept_suggestion', label: 'Accept Suggestion', effect: 'Replace with suggested text' },
    { option_id: 'skip', label: 'Skip', effect: 'Keep original' },
  ],
};

export const mockCsvContent = `spec_id,module_tag,module_role,requirement,acceptance_criteria
SPEC-001,AUTH,Authentication,System shall authenticate users via OAuth2,User receives a valid JWT token
SPEC-002,EXPORT,Data Export,System shall export data to CSV,Downloaded file contains all visible rows`;

export const stderrLines = {
  loadOk: '[PIKA] Load: ok \u2014 Loaded 2 specs',
  decompRunning: '[PIKA] Decomposition: running \u2014 Analyzing spec relationships',
  decompDone: '[PIKA] Decomposition: ok \u2014 No splits or merges needed',
  decompSkipped: '[PIKA] Decomposition: skipped \u2014 Disabled by config',
  decompBlocked: '[PIKA] Decomposition: blocked \u2014 Split candidates found',
  agentsRunning: '[PIKA] Agents: running \u2014 Starting ambiguity and testability agents',
  agentsFailed: '[PIKA] Agents: failed \u2014 Agent timeout',
  refineOk: '[PIKA] Refine: ok \u2014 All specs passed',
  refineBlocked: '[PIKA] Refine: blocked \u2014 2 items need review',
  loadFailed: '[PIKA] Load: failed \u2014 Missing required columns',
  invalidLine: 'Some random log line without PIKA format',
  malformed: '[PIKA] BadFormat',

  // Implement steps
  workspaceOk: '[PIKA] Workspace: ok \u2014 run impl-001',
  catalogOk: '[PIKA] Catalog: ok \u2014 3 modules (AUTH, EXPORT, CORE)',
  appendixOk: '[PIKA] Appendix: ok \u2014 2 entries loaded (1 with IDs)',
  appendixFailed: '[PIKA] Appendix: failed \u2014 File not found',
  plannerRunning: '[PIKA] Planner: running \u2014 unified planner',
  plannerOk: '[PIKA] Planner: ok \u2014 3 modules, 2 anchors, 1 cross-dep, 4 contracts',
  plannerFailed: '[PIKA] Planner: failed \u2014 timeout',
  plannerBlocked: '[PIKA] Planner: blocked \u2014 2 manual resolution items',
  planValidationOk: '[PIKA] Plan validation: ok \u2014 DAG valid, all specs covered',
  planValidationBlocked: '[PIKA] Plan validation: blocked \u2014 dependency cycle requires manual resolution',
  contractFieldOk: '[PIKA] Contract field check: ok \u2014 all contract fields consistent',
  requiredFieldOk: '[PIKA] Required field coverage check: ok \u2014 contract fields are covered',
  batchPlanOk: '[PIKA] Batch plan: ok \u2014 3 batches',
  briefsOk: '[PIKA] Briefs: ok \u2014 3 batch briefs',
  briefValidationOk: '[PIKA] Brief validation: ok \u2014 all briefs batch-scoped',
  depCheckOk: '[PIKA] Dependency context edge check: ok \u2014 dependency context matches planner',
  depCheckFailed: '[PIKA] Dependency context edge check: failed \u2014 mismatch detected',
  executeRunning: '[PIKA] Execute: running \u2014 B0 (1/3)',
  executeOk: '[PIKA] Execute: ok \u2014 3 batches completed (parallel)',
  executeFailed: '[PIKA] Execute: failed \u2014 code_gen: timeout',
  executeBlocked: '[PIKA] Execute: blocked \u2014 B1 manual resolution',
};

export function buildGateItems(): ResolutionItem[] {
  return [
    {
      id: 'AMB-001',
      spec_ids: ['SPEC-001'],
      type: 'Ambiguity: Vague authentication requirement',
      reason: 'authenticate users',
      currentText: 'System shall authenticate users via OAuth2',
      suggestedText: 'System shall authenticate users via OAuth2 with PKCE flow',
      field: 'requirement',
      itemIndex: 0,
      options: [
        { id: 'accept_suggestion', label: 'Accept Suggestion', description: 'Replace with suggested text' },
        { id: 'let_agent_edit', label: 'Let Agent Edit', description: 'Agent will rewrite' },
        { id: 'skip', label: 'Skip', description: 'Keep original' },
      ],
    },
    {
      id: 'TST-001',
      spec_ids: ['SPEC-002'],
      type: 'Testability: Untestable acceptance criteria',
      reason: 'No measurable criterion for "all visible rows"',
      currentText: 'Downloaded file contains all visible rows',
      suggestedText: 'Downloaded CSV contains exactly N rows matching the current filter',
      field: 'acceptance_criteria',
      itemIndex: 1,
      options: [
        { id: 'accept_suggestion', label: 'Accept Suggestion', description: 'Replace with suggested text' },
        { id: 'skip', label: 'Skip', description: 'Keep original' },
      ],
    },
  ];
}

export const mockTextAppendix: Appendix = {
  id: 'appx-text-001',
  fileName: 'notes.txt',
  filePath: '/test/notes.txt',
  type: 'text',
  moduleTag: 'AUTH',
  content: 'Line one of notes\nLine two of notes\nLine three of notes',
};

export const mockTableAppendix: Appendix = {
  id: 'appx-table-001',
  fileName: 'data.csv',
  filePath: '/test/data.csv',
  type: 'table',
  moduleTag: 'EXPORT',
  content: 'name,value,status\nAlpha,100,active\nBeta,200,inactive\nGamma,300,active',
  columns: ['name', 'value', 'status'],
  parsedRows: [
    { name: 'Alpha', value: '100', status: 'active' },
    { name: 'Beta', value: '200', status: 'inactive' },
    { name: 'Gamma', value: '300', status: 'active' },
  ],
};

export const mockAppendixCsvContent = 'name,value,status\nAlpha,100,active\nBeta,200,inactive\nGamma,300,active';

export const mockPreferences: PikaPreferences = {
  version: 1,
  projectRootPath: '/test/project',
  designSpecPath: '/test/spec.csv',
  configPath: '/test/config.yaml',
  refineEnabled: true,
  implementEnabled: false,
  decompositionEnabled: true,
  appendixRefs: [
    { id: 'appx-text-001', fileName: 'notes.txt', filePath: '/test/notes.txt', type: 'text', moduleTag: 'AUTH' },
  ],
  availableModuleTags: ['AUTH', 'EXPORT'],
};
