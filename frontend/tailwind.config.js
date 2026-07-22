/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        primary: {
          DEFAULT: '#ffde59',
          dark: '#f5c400',
        },
        ink: '#121212',
        surface: {
          DEFAULT: '#1f1f1f',
          raised: '#262626',
          light: '#ffffff',
        },
        canvas: {
          dark: '#121212',
          light: '#f8f8f5',
        },
        muted: '#9CA3AF',
        border: {
          DEFAULT: 'rgba(255,255,255,0.1)',
          light: '#e5e7eb',
        },
        success: '#34D399',
        warning: '#F59E0B',
        danger: '#EF4444',
      },
      fontFamily: {
        display: ['Montserrat', 'sans-serif'],
        body: ['Poppins', 'sans-serif'],
      },
      borderRadius: {
        DEFAULT: '8px',
        lg: '12px',
        xl: '16px',
      },
      boxShadow: {
        soft: '0 4px 20px -4px rgba(0, 0, 0, 0.35)',
      },
    },
  },
  plugins: [],
}
