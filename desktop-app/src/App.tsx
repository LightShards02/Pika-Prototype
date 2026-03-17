import React, { useEffect } from 'react';
import { TopBar } from './components/TopBar';
import { SpecViewer } from './components/SpecViewer';
import { PipelineView } from './components/PipelineView';
import { GatePanel } from './components/GatePanel';
import { EntryScreen } from './components/EntryScreen';
import { useStore } from './store';

// Mock Data for Demonstration
const mockSpecs = [
  { spec_id: 'SPEC-001', module_tag: 'auth', module_role: 'provider', requirement: 'The system shall allow users to log in with email and password.', acceptance_criteria: 'Verify login success with valid credentials.', status: 'done' },
  { spec_id: 'SPEC-002', module_tag: 'auth', module_role: 'consumer', requirement: 'Users shall receive a JWT token upon successful authentication.', acceptance_criteria: 'Verify JWT presence in response.', status: 'done' },
  { spec_id: 'SPEC-003', module_tag: 'user_mgmt', module_role: 'provider', requirement: 'The user profile shall be updated when requested.', acceptance_criteria: 'Verify profile changes are persisted.', status: 'pending' },
  { spec_id: 'SPEC-004', module_tag: 'user_mgmt', module_role: 'consumer', requirement: 'Profiles shall include a display name and avatar URL.', acceptance_criteria: 'Verify fields in profile object.', status: 'pending' },
  { spec_id: 'SPEC-005', module_tag: 'billing', module_role: 'provider', requirement: 'Invoices shall be generated monthly for active subscriptions.', acceptance_criteria: 'Verify invoice generation logic.', status: 'pending' },
];

const mockGateItems = [
  {
    id: 'item-1',
    spec_ids: ['SPEC-003'],
    type: 'Ambiguity: Requirement underspecified',
    reason: 'No triggering condition, no actor, no latency/consistency spec.',
    currentText: 'The user profile shall be updated when requested.',
    suggestedText: 'When an authenticated user submits a profile update request via the PATCH /users/{id} endpoint, the system shall persist the change within 500ms and return the updated profile object.',
    options: [
      { id: 'accept', label: 'Accept suggestion', description: 'Accept the AI\'s proposed rewrite of the spec text' },
      { id: 'agent', label: 'Let agent edit', description: 'Delegate the fix to an AI agent (spec_editor)' },
      { id: 'skip', label: 'Keep as-is', description: 'Keep the spec unchanged and continue' }
    ]
  },
  {
    id: 'item-2',
    spec_ids: ['SPEC-005'],
    type: 'Testability Gap: Untestable criteria',
    reason: 'Criteria "Verify invoice generation logic" is too broad and cannot be deterministically verified.',
    currentText: 'Verify invoice generation logic.',
    suggestedText: 'Verify that an invoice record is created in the Billing table with status="PENDING" and total_amount matching the sum of active subscription line items.',
    options: [
      { id: 'accept', label: 'Accept suggestion', description: 'Accept the AI\'s proposed rewrite of the spec text' },
      { id: 'agent', label: 'Let agent edit', description: 'Delegate the fix to an AI agent (spec_editor)' },
      { id: 'skip', label: 'Keep as-is', description: 'Keep the spec unchanged and continue' }
    ]
  }
];

function App() {
  const { setSpecs, setCurrentGateItems, setRun, updatePhase } = useStore();
  const { run } = useStore();

  useEffect(() => {
    // Initialize mock data
    setSpecs(mockSpecs);
    setCurrentGateItems(mockGateItems);
    
    // Simulate initial run state after 1 second
    const timer = setTimeout(() => {
      setRun({ 
        status: 'running', 
        progress: 15, 
        runId: '4', 
        specPath: 'my-spec.csv' 
      });
      updatePhase('R1', { status: 'done' });
      updatePhase('R2', { status: 'done' });
      updatePhase('R3', { status: 'running' });
      
      // Pause at gate after 3 seconds
      setTimeout(() => {
        setRun({ status: 'paused', progress: 38 });
        updatePhase('R3', { status: 'blocked' });
      }, 2000);
    }, 1000);

    return () => clearTimeout(timer);
  }, []);

  if (run.status === 'idle') {
    return <EntryScreen />;
  }

  return (
    <div className="flex flex-col h-screen bg-bg-primary select-none">
      <TopBar />
      
      <main className="flex flex-1 overflow-hidden">
        {/* Left Panel: Spec Viewer */}
        <div className="w-[45%] flex-shrink-0">
          <SpecViewer />
        </div>

        {/* Right Panel: Pipeline or Gate */}
        <div className="flex-1 overflow-hidden relative">
          {run.status === 'paused' ? (
            <div className="absolute inset-0 z-20 animate-in fade-in slide-in-from-right-4 duration-300">
              <GatePanel />
            </div>
          ) : (
            <PipelineView />
          )}
        </div>
      </main>
    </div>
  );
}

export default App;
