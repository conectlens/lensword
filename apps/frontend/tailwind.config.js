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
      keyframes: {
        // A freshly-dealt flashcard (issue: flashcard animation). Applied to
        // the whole FlashcardStack, which already remounts per word via
        // `key={word.id}` in FlashcardSessionPage — the remount restarts
        // this animation for every new card with no extra state needed.
        'card-enter': {
          '0%': { opacity: '0', transform: 'translateY(12px) scale(0.97)' },
          '100%': { opacity: '1', transform: 'translateY(0) scale(1)' },
        },
        // The reveal flip. A true rotateY flip needs both faces present in
        // the DOM at once (front and back overlaid, back only hidden via
        // backface-visibility) — but FlashcardStack keeps only the current
        // face's content in the DOM at all times (see FlashcardStack.test.tsx,
        // which asserts the hidden translation is genuinely absent, not just
        // visually hidden). Pinching the card to zero width, swapping the
        // single face's content, and expanding back reads as the same
        // "flip" gesture without needing two faces to coexist.
        'card-flip': {
          '0%': { transform: 'scaleX(1)' },
          '50%': { transform: 'scaleX(0)' },
          '100%': { transform: 'scaleX(1)' },
        },
      },
      animation: {
        'card-enter': 'card-enter 320ms ease-out',
        'card-flip': 'card-flip 320ms ease-in-out',
      },
    },
  },
  plugins: [],
}
