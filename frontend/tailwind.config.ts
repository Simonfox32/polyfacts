import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        verdict: {
          true: "#22c55e",
          "mostly-true": "#84cc16",
          "half-true": "#eab308",
          "mostly-false": "#f97316",
          false: "#ef4444",
          unverified: "#6b7280",
        },
      },
    },
  },
  plugins: [],
};

export default config;
