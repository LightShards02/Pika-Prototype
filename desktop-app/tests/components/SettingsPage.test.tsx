import { describe, it, expect, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SettingsPage } from '../../src/components/SettingsPage';
import { useStore } from '../../src/store';

const sampleYaml = `version: 1
project:
  name: TestProject
  root_dir: /test
  state:
    design_spec_path: spec.csv
    id_registry_path: out/state/id_registry.json
    sads_id_mapping_path: out/state/sads_id_mapping.json
default_outputs:
  log_dir: out/logs
id_generation:
  id_registry: out/state/id_registry.json
logging:
  level: INFO
  verbose_level: DEBUG
  json: false
`;

describe('SettingsPage', () => {
  it('shows browse/create buttons when no config path', () => {
    render(<SettingsPage />);
    expect(screen.getByText('No Configuration File')).toBeInTheDocument();
    expect(screen.getByText('Browse...')).toBeInTheDocument();
    expect(screen.getByText('Create from Template')).toBeInTheDocument();
  });

  it('loads and renders form when config path is set', async () => {
    vi.mocked(window.electronAPI.readFile).mockResolvedValue(sampleYaml);
    useStore.setState({ configPath: '/test/config.yaml' });
    render(<SettingsPage />);

    await waitFor(() => {
      expect(screen.getByText('Project')).toBeInTheDocument();
    });
  });

  it('shows mode toggle buttons', async () => {
    vi.mocked(window.electronAPI.readFile).mockResolvedValue(sampleYaml);
    useStore.setState({ configPath: '/test/config.yaml' });
    render(<SettingsPage />);

    await waitFor(() => {
      expect(screen.getByText('Form')).toBeInTheDocument();
      expect(screen.getByText('Raw YAML')).toBeInTheDocument();
    });
  });

  it('switches to raw mode and shows textarea', async () => {
    const user = userEvent.setup();
    vi.mocked(window.electronAPI.readFile).mockResolvedValue(sampleYaml);
    useStore.setState({ configPath: '/test/config.yaml' });
    render(<SettingsPage />);

    await waitFor(() => {
      expect(screen.getByText('Raw YAML')).toBeInTheDocument();
    });

    await user.click(screen.getByText('Raw YAML'));

    await waitFor(() => {
      const textarea = document.querySelector('textarea');
      expect(textarea).toBeInTheDocument();
      expect(textarea?.value).toContain('TestProject');
    });
  });

  it('save button calls writeFile', async () => {
    const user = userEvent.setup();
    vi.mocked(window.electronAPI.readFile).mockResolvedValue(sampleYaml);
    useStore.setState({ configPath: '/test/config.yaml' });
    render(<SettingsPage />);

    // Wait for form to load
    await waitFor(() => {
      expect(screen.getByText('Project')).toBeInTheDocument();
    });

    // Switch to raw mode and make a change to enable dirty state
    await user.click(screen.getByText('Raw YAML'));
    await waitFor(() => {
      expect(document.querySelector('textarea')).toBeInTheDocument();
    });

    const textarea = document.querySelector('textarea')!;
    await user.type(textarea, '\n# comment');

    // Save button should be enabled now
    await user.click(screen.getByText('Save'));

    await waitFor(() => {
      expect(window.electronAPI.writeFile).toHaveBeenCalledWith(
        '/test/config.yaml',
        expect.any(String),
      );
    });
  });

  it('browse config calls openFileDialog', async () => {
    const user = userEvent.setup();
    vi.mocked(window.electronAPI.openFileDialog).mockResolvedValue('/chosen/config.yaml');
    render(<SettingsPage />);

    await user.click(screen.getByText('Browse...'));
    expect(window.electronAPI.openFileDialog).toHaveBeenCalled();

    await waitFor(() => {
      expect(useStore.getState().configPath).toBe('/chosen/config.yaml');
    });
  });

  it('shows error state when config fails to load', async () => {
    vi.mocked(window.electronAPI.readFile).mockRejectedValue(new Error('File not found'));
    useStore.setState({ configPath: '/bad/path.yaml' });
    render(<SettingsPage />);

    await waitFor(() => {
      expect(screen.getByText('Failed to Load Config')).toBeInTheDocument();
      expect(screen.getByText(/File not found/)).toBeInTheDocument();
    });
  });
});
