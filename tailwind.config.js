/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./templates/**/*.html",
    "./**/templates/**/*.html",
  ],
  theme: {
    extend: {
      fontFamily: {
        display: ["Lato", "system-ui", "sans-serif"],
        body: ["Lato", "system-ui", "sans-serif"],
      },
      colors: {
        // Pathcipher brand palette (teal on light, mint accent).
        ink: "#212121",
        surface: "#f4f8f7",
        brand: {
          50: "#e6f4f1",
          100: "#c1e3dd",
          200: "#97d1c7",
          300: "#66bcae",
          400: "#33a493",
          500: "#138275",
          600: "#0f6a5f",
          700: "#00685b",
          800: "#083b34",
          900: "#04231f",
        },
        accent: "#4dffaf",
      },
    },
  },
  plugins: [
    require("@tailwindcss/forms"),
    require("@tailwindcss/typography"),
  ],
};
