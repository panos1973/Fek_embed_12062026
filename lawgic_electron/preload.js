'use strict';
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('api', {
  selectFolder: () => ipcRenderer.invoke('dialog:selectFolder'),
  startIngest: (folder) => ipcRenderer.invoke('pipeline:start', folder),
  retry: () => ipcRenderer.invoke('pipeline:retry'),
  cancel: () => ipcRenderer.send('pipeline:cancel'),
  getStatus: () => ipcRenderer.invoke('pipeline:status'),
  getReview: () => ipcRenderer.invoke('pipeline:review'),
  getSettings: () => ipcRenderer.invoke('settings:get'),
  saveSettings: (obj) => ipcRenderer.invoke('settings:save', obj),
  onPipelineEvent: (cb) => ipcRenderer.on('pipeline:event', (_e, o) => cb(o)),
  onPipelineDone: (cb) => ipcRenderer.on('pipeline:done', (_e, o) => cb(o)),
});
