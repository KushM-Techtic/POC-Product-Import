import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { ConfigProvider } from 'antd'
import './index.css'
import App from './App.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ConfigProvider
      theme={{
        token: {
          borderRadius: 8,
          colorPrimary: '#6366f1',
          colorSuccess: '#059669',
          colorWarning: '#d97706',
          colorError: '#dc2626',
          colorInfo: '#06b6d4',
          fontFamily: "'Inter', system-ui, -apple-system, sans-serif",
        },
        components: {
          Modal: { borderRadiusLG: 14 },
          Table: { borderRadius: 0 },
          Progress: { circleTextFontSize: '12px' },
        },
      }}
    >
      <App />
    </ConfigProvider>
  </StrictMode>,
)
