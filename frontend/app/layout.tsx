import type { Metadata } from 'next'
import './globals.css'
import { ToastProvider } from './components/Toast'
import { ThemeProvider } from './components/ThemeContext'
import LiveAlertPanel from './components/LiveAlertPanel'

export const metadata: Metadata = {
  title: 'FraudGuard XAI — Explainable AI Banking Security',
  description: 'Real-time fraud detection powered by XGBoost + SHAP',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=DM+Mono:wght@400;500&family=Outfit:wght@300;400;500;600;700;800&display=swap" rel="stylesheet" />
      </head>
      <body style={{ margin:0, padding:0 }}>
        <ThemeProvider>
          <ToastProvider>
            {children}
            {/* Global WebSocket alert panel — connects once, visible on all pages */}
            <LiveAlertPanel />
          </ToastProvider>
        </ThemeProvider>
      </body>
    </html>
  )
}
