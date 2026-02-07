/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        /* Semantic text colors */
        text: {
          primary: '#111827',   /* gray-900 */
          secondary: '#4b5563', /* gray-600 */
          muted: '#9ca3af',     /* gray-400 */
        },
        /* Semantic background colors */
        bg: {
          DEFAULT: '#ffffff',
          secondary: '#f3f4f6', /* gray-100 */
          tertiary: '#e5e7eb',  /* gray-200 */
        },
        /* Semantic border colors */
        border: {
          DEFAULT: '#e5e7eb',   /* gray-200 */
          soft: '#f3f4f6',      /* gray-100 */
        },
        /* Status colors */
        status: {
          error: '#ef4444',     /* red-500 */
          success: '#22c55e',   /* green-500 */
          warning: '#f59e0b',   /* amber-500 */
          pending: '#f59e0b',   /* amber-500 */
        },
        /* Accent */
        accent: {
          blue: '#2563eb',      /* blue-600 */
        },
        /* Button colors */
        btn: {
          primary: '#111827',         /* gray-900 */
          'primary-hover': '#1f2937', /* gray-800 */
        },
      },
      maxWidth: {
        chat: '768px',
      },
      animation: {
        'fade-in': 'fade-in 0.2s ease',
        'slide-up': 'slide-up 0.2s ease',
        'pulse-dot': 'pulse-dot 1.5s infinite',
      },
      keyframes: {
        'fade-in': {
          from: { opacity: '0' },
          to: { opacity: '1' },
        },
        'slide-up': {
          from: { opacity: '0', transform: 'translateY(4px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
        'pulse-dot': {
          '0%,100%': { opacity: '1' },
          '50%': { opacity: '0.3' },
        },
      },
    },
  },
  plugins: [],
}
