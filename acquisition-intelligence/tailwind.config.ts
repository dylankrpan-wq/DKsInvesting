import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Institutional dark palette (Bloomberg / TradingView inspired)
        base: {
          900: "#0a0e14", // app background
          800: "#0f141b", // panel background
          700: "#151b24", // card background
          600: "#1c2430", // raised / hover
          500: "#26313f", // borders strong
        },
        line: "#1e2732",
        ink: {
          100: "#e6edf3", // primary text
          300: "#9fb0c3", // secondary text
          500: "#5f7183", // muted text
        },
        accent: {
          DEFAULT: "#3b82f6",
          cyan: "#22d3ee",
        },
        pos: "#22c55e", // positive / buy
        neg: "#ef4444", // negative / avoid
        warn: "#f59e0b", // caution / watch
      },
      fontFamily: {
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
      },
      boxShadow: {
        panel: "0 1px 0 0 rgba(255,255,255,0.02), 0 8px 24px -12px rgba(0,0,0,0.6)",
      },
    },
  },
  plugins: [],
};

export default config;
