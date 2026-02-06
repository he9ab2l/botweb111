/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        bg: { DEFAULT: '#0b0f14', secondary: '#0f172a', tertiary: '#111827' },
        border: { DEFAULT: '#1f2933', soft: '#18202a', hover: '#263241' },
        text: { primary: '#e6edf3', secondary: '#9da7b3', muted: '#6b7280' },
        accent: { blue: '#3b82f6' },
        status: {
          running: '#3b82f6',
          success: '#22c55e',
          error: '#ef4444',
          pending: '#f59e0b',
        },
        btn: { primary: '#3b82f6', 'primary-hover': '#2563eb' },
        bubble: {
          user: 'rgba(59,130,246,0.05)',
          assistant: '#0f172a',
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
