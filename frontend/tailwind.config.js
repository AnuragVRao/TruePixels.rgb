/**
 * Theme colours come from CSS variables in src/index.css (light by default,
 * dark under class="dark"). Each is wrapped in color-mix so opacity modifiers
 * such as bg-primary/10 or bg-card/60 work with plain hex variables.
 */
const token = (name) => `color-mix(in srgb, var(--${name}) calc(<alpha-value> * 100%), transparent)`;

/** Status colours: the solid colour, its text-on-solid colour, and a shade readable as text. */
const status = (name) => ({
  DEFAULT: token(name),
  foreground: token(`${name}-foreground`),
  text: token(`${name}-text`),
});

/** @type {import('tailwindcss').Config} */
export default {
  darkMode: ['class'],
  content: [
    './index.html',
    './src/**/*.{js,ts,jsx,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        border: token('border'),
        input: token('input'),
        ring: token('ring'),
        background: token('background'),
        foreground: token('foreground'),
        link: token('link'),
        primary: { DEFAULT: token('primary'), hover: token('primary-hover'), foreground: token('primary-foreground') },
        secondary: { DEFAULT: token('secondary'), foreground: token('secondary-foreground') },
        destructive: status('destructive'),
        success: status('success'),
        warning: status('warning'),
        info: status('info'),
        muted: { DEFAULT: token('muted'), foreground: token('muted-foreground') },
        accent: { DEFAULT: token('accent'), foreground: token('accent-foreground') },
        popover: { DEFAULT: token('popover'), foreground: token('popover-foreground') },
        card: { DEFAULT: token('card'), foreground: token('card-foreground') },
        footer: { DEFAULT: token('footer'), foreground: token('footer-foreground') },
        chart: {
          1: token('chart-1'),
          2: token('chart-2'),
          3: token('chart-3'),
          4: token('chart-4'),
          5: token('chart-5'),
        },
      },
      borderRadius: {
        xl: 'calc(var(--radius) + 4px)',
        lg: 'var(--radius)',
        md: 'calc(var(--radius) - 2px)',
        sm: 'calc(var(--radius) - 4px)',
      },
      fontFamily: {
        sans: ['var(--font-sans)'],
        serif: ['var(--font-serif)'],
        mono: ['var(--font-mono)'],
      },
    },
    // DBIM §4.3 type scale: six sizes only, switched for mobile in index.css.
    fontSize: {
      xs: ['var(--fs-small)', { lineHeight: '1.5' }],
      sm: ['var(--fs-p2)', { lineHeight: '1.5' }],
      base: ['var(--fs-p1)', { lineHeight: '1.5' }],
      lg: ['var(--fs-h3)', { lineHeight: '1.4' }],
      xl: ['var(--fs-h3)', { lineHeight: '1.4' }],
      '2xl': ['var(--fs-h2)', { lineHeight: '1.3' }],
      '3xl': ['var(--fs-h1)', { lineHeight: '1.2' }],
      '4xl': ['var(--fs-h1)', { lineHeight: '1.2' }],
      '5xl': ['var(--fs-h1)', { lineHeight: '1.2' }],
    },
  },
  plugins: [],
};
