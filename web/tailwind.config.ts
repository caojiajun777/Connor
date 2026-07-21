import type { Config } from "tailwindcss";

export default {
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        background: "var(--background)",
        surface: "var(--surface)",
        "surface-secondary": "var(--surface-secondary)",
        "surface-dark": "var(--surface-dark)",
        "text-primary": "var(--text-primary)",
        "text-secondary": "var(--text-secondary)",
        "text-tertiary": "var(--text-tertiary)",
        "text-quaternary": "var(--text-quaternary)",
        "text-inverse": "var(--text-inverse)",
        "ink-soft": "var(--ink-soft)",
        muted: "var(--muted)",
        hairline: "var(--hairline)",
        signal: "var(--signal)",
        border: "var(--border)",
        "border-strong": "var(--border-strong)",
        accent: "var(--accent)",
        "accent-soft": "var(--accent-soft)",
        "accent-2": "var(--accent-2)",
        "accent-3": "var(--accent-3)",
        "accent-4": "var(--accent-4)",
        "accent-light": "var(--accent-light)",
        "accent-dark": "var(--accent-dark)",
        "surface-solid": "var(--surface-solid)",
        "surface-elevated": "var(--surface-elevated)",
        success: "var(--success)",
        warning: "var(--warning)",
        danger: "var(--danger)",
      },
      borderRadius: {
        xs: "var(--radius-xs)",
        sm: "var(--radius-sm)",
        md: "var(--radius-md)",
        pill: "var(--radius-pill)",
        small: "var(--radius-small)",
        medium: "var(--radius-medium)",
        large: "var(--radius-large)",
      },
      maxWidth: {
        content: "var(--content-width)",
        shell: "var(--shell-width)",
      },
      fontFamily: {
        sans: ["var(--font-sf-text)"],
        display: ["var(--font-sf-display)"],
        mono: ["var(--font-sf-mono)"],
      },
      boxShadow: {
        soft: "0 1px 2px rgba(0,0,0,0.04), 0 4px 16px rgba(0,0,0,0.04)",
      },
    },
  },
  plugins: [],
} satisfies Config;
