const { app, BrowserWindow, ipcMain, dialog } = require('electron');
const path = require('path');
const fs = require('fs');
const { spawn } = require('child_process');
const yaml = require('js-yaml');

let mainWindow;
let pikaProcess = null;

/**
 * Directory that contains cli.py, config/, core/, handlers/ (PIKA Python backend).
 * Override when the app runs from a layout where ../backend is wrong or stale:
 *   set PIKA_BACKEND_ROOT to an absolute path, e.g. C:\Work\Pika\backend
 */
function resolvePikaBackendRoot() {
  const raw = process.env.PIKA_BACKEND_ROOT;
  if (raw != null && String(raw).trim()) {
    return path.resolve(String(raw).trim());
  }
  return path.resolve(__dirname, '..', 'backend');
}

const PIKA_ROOT = resolvePikaBackendRoot();

/**
 * Warn once if the backend's JSON schema cannot validate refine consensus keys.
 * Prevents silent "additional properties" failures when the UI points at an updated project config
 * but Electron still spawns an older PIKA checkout.
 */
function warnIfRefineConsensusSchemaMissing() {
  const schemaPath = path.join(PIKA_ROOT, 'config', 'config.schema.json');
  try {
    if (!fs.existsSync(schemaPath)) {
      console.warn(
        `[PIKA desktop] Missing ${schemaPath}. Check PIKA_BACKEND_ROOT (currently ${PIKA_ROOT}).`,
      );
      return;
    }
    const doc = JSON.parse(fs.readFileSync(schemaPath, 'utf8'));
    const refineProps = doc?.properties?.commands?.properties?.refine?.properties;
    if (!refineProps || !Object.prototype.hasOwnProperty.call(refineProps, 'agent_replicas')) {
      console.warn(
        '[PIKA desktop] This PIKA backend config.schema.json is missing commands.refine.agent_replicas. ',
        'Project configs that set agent_replicas / consensus_min_votes will fail validation. ',
        `Pull the latest PIKA repo or set PIKA_BACKEND_ROOT to a backend that includes those keys. Using: ${PIKA_ROOT}`,
      );
    }
  } catch (err) {
    console.warn('[PIKA desktop] Could not read config.schema.json:', err.message);
  }
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 800,
    minHeight: 600,
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      nodeIntegration: false,
      contextIsolation: true,
    },
  });

  // In development, load from Vite dev server
  if (process.env.NODE_ENV === 'development') {
    mainWindow.loadURL('http://localhost:5173');
    mainWindow.webContents.openDevTools();
  } else {
    mainWindow.loadFile(path.join(__dirname, 'dist/index.html'));
  }
}

app.whenReady().then(() => {
  warnIfRefineConsensusSchemaMissing();
  createWindow();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});

// ---------------------------------------------------------------------------
// Shared: spawn a PIKA CLI command via conda
// ---------------------------------------------------------------------------

function spawnPikaCommand(args) {
  // Quote any arg containing spaces so shell: true doesn't split them
  const safeArgs = args.map((a) => (typeof a === 'string' && a.includes(' ')) ? `"${a}"` : a);
  const condaArgs = ['run', '-n', 'Local', 'python', '-m', 'cli', ...safeArgs];
  const child = spawn('conda', condaArgs, {
    cwd: PIKA_ROOT,
    shell: true,
    stdio: ['ignore', 'pipe', 'pipe'],
  });

  let stdoutBuf = '';

  child.stdout.on('data', (chunk) => {
    stdoutBuf += chunk.toString();
  });

  child.stderr.on('data', (chunk) => {
    const lines = chunk.toString().split(/\r?\n/).filter(Boolean);
    for (const line of lines) {
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.webContents.send('pika:stderr', line);
      }
    }
  });

  child.on('close', (code) => {
    let summary = null;
    try {
      summary = JSON.parse(stdoutBuf.trim());
    } catch {
      // stdout may not be valid JSON (e.g. if command crashed)
    }
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('pika:exit', { code, summary });
    }
    if (pikaProcess === child) {
      pikaProcess = null;
    }
  });

  child.on('error', (err) => {
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('pika:stderr', `[ELECTRON] Process error: ${err.message}`);
      mainWindow.webContents.send('pika:exit', { code: 1, summary: null });
    }
    if (pikaProcess === child) {
      pikaProcess = null;
    }
  });

  return child;
}

/**
 * Promise-based spawn for short-lived request/response CLI calls.
 * Does NOT use the global pikaProcess singleton.
 */
function spawnPikaCommandAsync(args) {
  return new Promise((resolve, reject) => {
    // Quote any arg containing spaces so shell: true doesn't split them
    const safeArgs = args.map((a) => (typeof a === 'string' && a.includes(' ')) ? `"${a}"` : a);
    const condaArgs = ['run', '-n', 'Local', 'python', '-m', 'cli', ...safeArgs];
    const child = spawn('conda', condaArgs, {
      cwd: PIKA_ROOT,
      shell: true,
      stdio: ['ignore', 'pipe', 'pipe'],
    });

    let stdoutBuf = '';
    const stderrLines = [];

    child.stdout.on('data', (chunk) => {
      stdoutBuf += chunk.toString();
    });

    child.stderr.on('data', (chunk) => {
      const lines = chunk.toString().split(/\r?\n/).filter(Boolean);
      for (const line of lines) {
        stderrLines.push(line);
        if (mainWindow && !mainWindow.isDestroyed()) {
          mainWindow.webContents.send('pika:stderr', line);
        }
      }
    });

    child.on('close', (code) => {
      let summary = null;
      try {
        summary = JSON.parse(stdoutBuf.trim());
      } catch {
        // stdout may not be valid JSON
      }
      resolve({ code, summary, stderrLines });
    });

    child.on('error', (err) => reject(err));
  });
}

// ---------------------------------------------------------------------------
// IPC Handlers: File System (existing)
// ---------------------------------------------------------------------------

ipcMain.handle('read-file', async (event, filePath) => {
  try {
    return fs.readFileSync(filePath, 'utf-8');
  } catch (error) {
    console.error('Error reading file:', error);
    throw error;
  }
});

ipcMain.handle('write-file', async (event, filePath, content) => {
  try {
    fs.writeFileSync(filePath, content, 'utf-8');
    return true;
  } catch (error) {
    console.error('Error writing file:', error);
    throw error;
  }
});

ipcMain.handle('list-directory', async (event, dirPath) => {
  try {
    return fs.readdirSync(dirPath);
  } catch (error) {
    console.error('Error listing directory:', error);
    throw error;
  }
});

// ---------------------------------------------------------------------------
// IPC Handlers: File/Folder Dialogs
// ---------------------------------------------------------------------------

ipcMain.handle('dialog:openFile', async (_event, options) => {
  const filters = options?.filters || [{ name: 'All Files', extensions: ['*'] }];
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ['openFile'],
    filters,
  });
  if (result.canceled || result.filePaths.length === 0) return null;
  return result.filePaths[0];
});

ipcMain.handle('dialog:saveFile', async (_event, options) => {
  const filters = options?.filters || [{ name: 'YAML Files', extensions: ['yaml', 'yml'] }];
  const result = await dialog.showSaveDialog(mainWindow, {
    filters,
    defaultPath: options?.defaultPath,
  });
  if (result.canceled) return null;
  return result.filePath;
});

ipcMain.handle('pika:getRoot', () => PIKA_ROOT);

ipcMain.handle('dialog:openDir', async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ['openDirectory'],
  });
  if (result.canceled || result.filePaths.length === 0) return null;
  return result.filePaths[0];
});

// ---------------------------------------------------------------------------
// IPC Handlers: PIKA Refine Process Lifecycle
// ---------------------------------------------------------------------------

ipcMain.handle('pika:start-refine', async (_event, { projectRoot, configPath, designSpecPath }) => {
  if (pikaProcess) {
    throw new Error('A PIKA process is already running. Cancel it first.');
  }

  const args = ['agent', 'refine', '--project-root', projectRoot];
  if (configPath) args.push('--config', configPath);
  if (designSpecPath) args.push('--design-spec', designSpecPath);

  pikaProcess = spawnPikaCommand(args);
});

ipcMain.handle('pika:cancel', async () => {
  if (pikaProcess) {
    pikaProcess.kill();
    pikaProcess = null;
  }
});

ipcMain.handle('pika:start-implement', async (_event, { projectRoot, configPath, designSpecPath }) => {
  if (pikaProcess) {
    throw new Error('A PIKA process is already running. Cancel it first.');
  }

  const args = ['agent', 'implement', '--project-root', projectRoot];
  if (configPath) args.push('--config', configPath);
  if (designSpecPath) args.push('--design-spec', designSpecPath);

  pikaProcess = spawnPikaCommand(args);
});

// ---------------------------------------------------------------------------
// IPC Handlers: Gate I/O
// ---------------------------------------------------------------------------

ipcMain.handle('pika:read-gate', async (_event, { runDir }) => {
  // Discover which stage file to read.
  // Implement writes manual_resolution/{stage}.json and records the stage in run_meta.json.
  // Refine writes manual_resolution/agent_review.json (no run_meta.json entry needed).
  let stageName = null;
  try {
    const runMetaPath = path.join(runDir, 'run_meta.json');
    const meta = JSON.parse(fs.readFileSync(runMetaPath, 'utf-8'));
    if (meta.blocked_at_stage) stageName = meta.blocked_at_stage;
  } catch {
    // run_meta.json absent or unreadable — fall through to agent_review.json
  }

  const candidates = [];
  if (stageName) candidates.push(path.join(runDir, 'manual_resolution', `${stageName}.json`));
  candidates.push(path.join(runDir, 'manual_resolution', 'agent_review.json'));

  let lastError;
  for (const filePath of candidates) {
    try {
      return JSON.parse(fs.readFileSync(filePath, 'utf-8'));
    } catch (err) {
      lastError = err;
    }
  }
  console.error('Error reading gate output:', lastError);
  throw lastError;
});

ipcMain.handle('pika:write-resolution', async (_event, { runDir, resolutions }) => {
  const resolutionsPath = path.join(runDir, 'manual_resolution', 'resolutions.yaml');
  try {
    const content = fs.readFileSync(resolutionsPath, 'utf-8');
    const data = yaml.load(content);

    for (const { itemIndex, chosenOptionId, editorOutput } of resolutions) {
      if (data.items && data.items[itemIndex]) {
        data.items[itemIndex].chosen_option_id = chosenOptionId;
        if (editorOutput) {
          data.items[itemIndex].editor_output = editorOutput;
        }
      }
    }

    fs.writeFileSync(resolutionsPath, yaml.dump(data, { lineWidth: -1 }), 'utf-8');
  } catch (error) {
    console.error('Error writing resolution:', error);
    throw error;
  }
});

// ---------------------------------------------------------------------------
// IPC Handlers: Resolve (apply-only) + Resume
// ---------------------------------------------------------------------------

ipcMain.handle('pika:apply-resolutions', async (_event, { projectRoot, runId, configPath }) => {
  if (pikaProcess) {
    throw new Error('A PIKA process is already running.');
  }

  const args = ['agent', 'resolve', '--run', runId, '--project-root', projectRoot, '--apply-only'];
  if (configPath) args.push('--config', configPath);

  pikaProcess = spawnPikaCommand(args);
});

ipcMain.handle('pika:resume-refine', async (_event, { projectRoot, runId, configPath }) => {
  if (pikaProcess) {
    throw new Error('A PIKA process is already running.');
  }

  const args = ['agent', 'refine', '--resume', '--run', runId, '--project-root', projectRoot];
  if (configPath) args.push('--config', configPath);

  pikaProcess = spawnPikaCommand(args);
});

ipcMain.handle('pika:resume-implement', async (_event, { projectRoot, runId, configPath }) => {
  if (pikaProcess) {
    throw new Error('A PIKA process is already running.');
  }

  const args = ['agent', 'implement', '--resume', '--run', runId, '--project-root', projectRoot];
  if (configPath) args.push('--config', configPath);

  pikaProcess = spawnPikaCommand(args);
});

// ---------------------------------------------------------------------------
// IPC Handler: Invoke spec_editor for a single gate item (desktop agent-edit)
// ---------------------------------------------------------------------------

ipcMain.handle('pika:invoke-spec-editor', async (_event, { projectRoot, runId, itemIndex, userGuide, configPath }) => {
  const args = [
    'agent', 'resolve',
    '--run', runId,
    '--project-root', projectRoot,
    '--invoke-editor',
    '--item-index', String(itemIndex),
  ];
  if (userGuide) args.push('--user-guide', userGuide);
  if (configPath) args.push('--config', configPath);

  const { code, summary, stderrLines } = await spawnPikaCommandAsync(args);

  console.log('[invoke-spec-editor] exit code:', code);
  console.log('[invoke-spec-editor] summary:', JSON.stringify(summary, null, 2));
  if (stderrLines.length > 0) {
    console.log('[invoke-spec-editor] stderr (last 10):', stderrLines.slice(-10).join('\n'));
  }

  if (code !== 0 || !summary || summary.status !== 'completed') {
    // Surface the real error from stderr
    const pikaErrors = stderrLines.slice(-5).join(' | ');
    const reason = summary?.reason || 'spec_editor invocation failed';
    throw new Error(pikaErrors ? `${reason} — ${pikaErrors}` : `${reason} (exit code: ${code})`);
  }

  return summary;
});

// ---------------------------------------------------------------------------
// IPC Handlers: Preferences Persistence
// ---------------------------------------------------------------------------

const PREFS_FILENAME = 'pika-preferences.json';

function getPrefsPath() {
  return path.join(app.getPath('userData'), PREFS_FILENAME);
}

ipcMain.handle('preferences:load', async () => {
  const prefsPath = getPrefsPath();
  try {
    if (!fs.existsSync(prefsPath)) {
      return null;
    }
    const content = fs.readFileSync(prefsPath, 'utf-8');
    return JSON.parse(content);
  } catch (error) {
    console.error('Error loading preferences:', error);
    return null;
  }
});

ipcMain.handle('preferences:save', async (_event, preferences) => {
  const prefsPath = getPrefsPath();
  try {
    const content = JSON.stringify(preferences, null, 2);
    fs.writeFileSync(prefsPath, content, 'utf-8');
    return true;
  } catch (error) {
    console.error('Error saving preferences:', error);
    return false;
  }
});

ipcMain.handle('preferences:pathExists', async (_event, targetPath) => {
  try {
    return fs.existsSync(targetPath);
  } catch {
    return false;
  }
});
