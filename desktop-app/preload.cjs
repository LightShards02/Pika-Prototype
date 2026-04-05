const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  // Existing file I/O
  readFile: (filePath) => ipcRenderer.invoke('read-file', filePath),
  writeFile: (filePath, content) => ipcRenderer.invoke('write-file', filePath, content),
  listDirectory: (dirPath) => ipcRenderer.invoke('list-directory', dirPath),

  // File/folder dialogs
  openFileDialog: (options) => ipcRenderer.invoke('dialog:openFile', options),
  openDirDialog: () => ipcRenderer.invoke('dialog:openDir'),
  saveFileDialog: (options) => ipcRenderer.invoke('dialog:saveFile', options),

  // PIKA root path
  getPikaRoot: () => ipcRenderer.invoke('pika:getRoot'),

  // PIKA CLI process lifecycle
  startRefine: (args) => ipcRenderer.invoke('pika:start-refine', args),
  startImplement: (args) => ipcRenderer.invoke('pika:start-implement', args),
  cancelPika: () => ipcRenderer.invoke('pika:cancel'),

  // Gate I/O
  readGateOutput: (args) => ipcRenderer.invoke('pika:read-gate', args),
  writeResolution: (args) => ipcRenderer.invoke('pika:write-resolution', args),

  // Resolve + Resume
  applyResolutions: (args) => ipcRenderer.invoke('pika:apply-resolutions', args),
  resumeRefine: (args) => ipcRenderer.invoke('pika:resume-refine', args),
  resumeImplement: (args) => ipcRenderer.invoke('pika:resume-implement', args),

  // Spec editor invocation (single-item agent edit for desktop gate)
  invokeSpecEditor: (args) => ipcRenderer.invoke('pika:invoke-spec-editor', args),

  // Preferences persistence
  loadPreferences: () => ipcRenderer.invoke('preferences:load'),
  savePreferences: (prefs) => ipcRenderer.invoke('preferences:save', prefs),
  pathExists: (targetPath) => ipcRenderer.invoke('preferences:pathExists', targetPath),

  // Event listeners (main → renderer)
  onPikaStderr: (callback) => {
    const handler = (_event, line) => callback(line);
    ipcRenderer.on('pika:stderr', handler);
    return () => ipcRenderer.removeListener('pika:stderr', handler);
  },
  onPikaExit: (callback) => {
    const handler = (_event, data) => callback(data);
    ipcRenderer.on('pika:exit', handler);
    return () => ipcRenderer.removeListener('pika:exit', handler);
  },
});
