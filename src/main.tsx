import React from 'react';
import ReactDOM from 'react-dom/client';
import { App } from '@/app';
import { bootstrapTheme } from '@/hooks/use-theme';
import '@/i18n';
import '@/styles/global.css';

bootstrapTheme();

const rootEl = document.getElementById('root');
if (!rootEl) {
  throw new Error('Root element #root not found');
}

ReactDOM.createRoot(rootEl).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
