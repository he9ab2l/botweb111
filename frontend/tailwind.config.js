/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        bg: { DEFAULT: '#f7f7f6', secondary: '#ffffff', tertiary: '#f1f5f9' },
        border: { DEFAULT: '#e2e8f0', soft: '#edf2f7', hover: '#cbd5e1' },
        text: { primary: '#0f172a', secondary: '#334155', muted: '#64748b' },
        accent: { blue: '#2563eb' },
        status: {
          running: '#2563eb',
          success: '#16a34a',
          error: '#dc2626',
          pending: '#d97706',
        },
        btn: { primary: '#2563eb', 'primary-hover': '#1d4ed8' },
        bubble: {
          user: 'rgba(37,99,235,0.08)',
          assistant: '#ffffff',
        },
      },
      fontFamily: {
        sans: ['-apple-system', 'BlinkMacSystemFont', '"Segoe UI"', 'Roboto', 'sans-serif'],
        mono: ['"SF Mono"', 'Monaco', '"Cascadia Code"', '"Fira Code"', 'monospace'],
      },
      maxWidth: {
        chat: '860px',
      },
      borderRadius: {
        bubble: '11px',
      },
      animation: {
        'pulse-dot': 'pulse-dot 1.5s infinite',
        'blink': 'blink 1s infinite',
        'fade-in': 'fade-in 0.15s ease',
      },
      keyframes: {
        'pulse-dot': { '0%,100%': { opacity: '1' }, '50%': { opacity: '0.3' } },
        'blink': { '0%,100%': { opacity: '1' }, '50%': { opacity: '0' } },
        'fade-in': {
          from: { opacity: '0', transform: 'translateY(2px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
      },
    },
  },
  plugins: [],
}
