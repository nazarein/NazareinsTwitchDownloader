/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./src/**/*.{js,jsx,ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        zinc: {
          700: 'rgb(63 63 70)',
          800: 'rgb(39 39 42)',
          900: 'rgb(24 24 27)',
        },
        purple: {
          500: 'rgb(147 51 234)',
          600: 'rgb(126 34 206)',
        },
        gray: {
          400: 'rgb(156 163 175)',
          500: 'rgb(115 115 115)',
        },
      },
    },
  },
  plugins: [],
  darkMode: 'media',
}
