import { defineConfig } from 'vitepress'

// DOCS_BASE lets a deploy target override the site root without editing this
// file — e.g. a GitHub Pages project site with no custom domain needs
// `DOCS_BASE=/<repo-name>/` set when building. Defaults to '/', which is
// correct for local preview and for docs.lensword.conectlens.com (a custom
// domain, served from its own root) — the actual production case today.
const base = process.env.DOCS_BASE || '/'

export default defineConfig({
  title: 'LensWord Docs',
  description:
    'Documentation for LensWord: a vocabulary trainer built around spaced repetition and the memory-palace technique.',
  base,
  cleanUrls: true,
  lastUpdated: true,

  // CHANGELOG.md is @include'd verbatim into changelog/legacy.md. Its own
  // links use paths correct for viewing it at the repo root on GitHub (e.g.
  // `docs/adr/0002-...`, `docs/reference/changelog/index.md`, `.changes/README.md`),
  // which is deliberately branch-agnostic — rewriting them to this site's
  // routes would mean two different correct hrefs for the same source text.
  // Left as dead links here rather than edited.
  ignoreDeadLinks: [
    /^\.?\/?docs\/(adr\/|ai-model-verification|reference\/changelog\/)/,
    /^\.?\/?\.changes\//,
  ],
  // No leading slash: on Windows, a leading "/" makes this match as an
  // absolute path deep inside the underlying glob library's path-relative
  // math, which corrupts page discovery for the whole site (confirmed by
  // instrumenting node_modules/vitepress locally — not a config style
  // preference).
  srcExclude: ['internal/**'],

  // No production domain has been decided yet (see docs/internal/repo-audit.md) —
  // sitemap generation needs a real hostname, so it's left off rather than
  // pointing at a placeholder. Add a `sitemap: { hostname: '...' }` block
  // here once one exists.

  head: [
    ['link', { rel: 'icon', type: 'image/svg+xml', href: `${base}favicon.svg` }],
    ['link', { rel: 'icon', type: 'image/png', sizes: '32x32', href: `${base}favicon-32x32.png` }],
    ['link', { rel: 'icon', type: 'image/png', sizes: '16x16', href: `${base}favicon-16x16.png` }],
    ['link', { rel: 'apple-touch-icon', href: `${base}apple-touch-icon.png` }],
    ['meta', { name: 'theme-color', content: '#ffde59' }],
    ['meta', { property: 'og:type', content: 'website' }],
    ['meta', { property: 'og:image', content: `${base}og-image.png` }],
    ['meta', { name: 'twitter:card', content: 'summary_large_image' }],
  ],

  themeConfig: {
    logo: { src: '/lensword-icon.webp', alt: 'LensWord' },

    // Structured per Diátaxis (https://diataxis.fr/): Setup is the one
    // tutorial, Install is task-oriented how-to guides, Learn is
    // explanation, Reference is lookup material. Contributing/Support sit
    // outside the four quadrants as project/community pages.
    nav: [
      { text: 'Setup', link: '/setup/' },
      { text: 'Install', link: '/install/web-app' },
      { text: 'Learn', link: '/learn/choose-a-surface' },
      { text: 'Reference', link: '/reference/verification' },
      {
        text: 'GitHub',
        items: [
          { text: 'Repository', link: 'https://github.com/conectlens/lensword' },
          { text: 'Issues', link: 'https://github.com/conectlens/lensword/issues' },
          { text: 'Documentation epic (#268)', link: 'https://github.com/conectlens/lensword/issues/268' },
        ],
      },
    ],

    sidebar: [
      {
        text: 'Setup (tutorial)',
        items: [{ text: 'Getting started', link: '/setup/' }],
      },
      {
        text: 'Install (how-to guides)',
        items: [
          { text: 'Web Application', link: '/install/web-app' },
          { text: 'Desktop Application', link: '/install/desktop-app' },
          { text: 'Browser Extension', link: '/install/browser-extension' },
          { text: 'MCP Server & Local CLI', link: '/install/mcp-local-cli' },
          { text: 'Self-Hosting & Deployment', link: '/install/self-hosting' },
          { text: 'Local AI / Ollama', link: '/install/local-ai-ollama' },
          { text: 'Troubleshooting', link: '/install/troubleshooting' },
        ],
      },
      {
        text: 'Learn (explanation)',
        items: [
          { text: 'Choose your surface', link: '/learn/choose-a-surface' },
          { text: 'Architecture', link: '/learn/architecture' },
          { text: 'Brand assets', link: '/learn/brand' },
        ],
      },
      {
        text: 'Changelog & Releases',
        items: [
          { text: 'Changelog overview', link: '/reference/changelog/' },
          { text: 'Web Application', link: '/reference/changelog/web' },
          { text: 'Desktop Application', link: '/reference/changelog/desktop' },
          { text: 'Browser Extension', link: '/reference/changelog/browser-extension' },
          { text: 'MCP Server', link: '/reference/changelog/mcp' },
          { text: 'Local CLI', link: '/reference/changelog/local-cli' },
          { text: 'Main Branch Activity', link: '/reference/changelog/main-branch-activity' },
          { text: 'Legacy changelog', link: '/reference/changelog/legacy' },
          { text: 'Releases', link: '/reference/releases/' },
          { text: 'Releases & compatibility process', link: '/reference/releasing' },
        ],
      },
      {
        text: 'Trust',
        items: [
          { text: 'Verification levels', link: '/reference/trust/verification-levels' },
          { text: 'Release process', link: '/reference/trust/release-process' },
          { text: 'Compatibility matrix', link: '/reference/trust/compatibility' },
          { text: 'Verification & known gaps', link: '/reference/verification' },
          { text: 'AI model verification log', link: '/reference/ai-model-verification' },
        ],
      },
      {
        text: 'Reference',
        items: [
          { text: 'MCP remote transport', link: '/reference/mcp-remote-transport' },
          { text: 'AI Companion guide', link: '/reference/mcp-companion-guide' },
          { text: 'Local development', link: '/reference/local-development' },
          { text: 'Architecture decision records', link: '/reference/adr/' },
        ],
      },
      {
        text: 'Project',
        items: [
          { text: 'Contributing', link: '/contributing' },
          { text: 'Sponsorship & support', link: '/support' },
        ],
      },
    ],

    editLink: {
      pattern: 'https://github.com/conectlens/lensword/edit/development/docs/:path',
      text: 'Edit this page on GitHub',
    },

    search: {
      provider: 'local',
    },

    socialLinks: [{ icon: 'github', link: 'https://github.com/conectlens/lensword' }],

    footer: {
      message: 'Released under the MIT License. No tagged release exists yet — see the Trust section.',
      copyright: 'Copyright © 2026 LensWord contributors',
    },
  },
})
