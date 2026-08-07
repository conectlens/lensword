---
layout: home
title: LensWord Docs
description: Documentation for LensWord — a vocabulary trainer built around spaced repetition and the memory-palace technique.

hero:
  name: LensWord
  text: Learn words that stick.
  tagline: Spaced repetition, forced recall, and memory-palace visualization — across a web app, desktop shell, browser extension, and MCP server.
  image:
    src: /lensword-icon.webp
    alt: LensWord
  actions:
    - theme: brand
      text: Setup (5 min tutorial)
      link: /setup/
    - theme: alt
      text: Choose your surface
      link: /learn/choose-a-surface
    - theme: alt
      text: View on GitHub
      link: https://github.com/conectlens/lensword

features:
  - icon: 🚀
    title: Setup
    details: "A hands-on tutorial: run LensWord end to end with Docker Compose and see it work in minutes. Start here if you're new."
    link: /setup/
    linkText: Start the tutorial
  - icon: 🧩
    title: Install
    details: Task-oriented how-to guides for every surface — web, desktop, browser extension, MCP server, self-hosting, local AI — plus troubleshooting.
    link: /install/web-app
    linkText: Browse install guides
  - icon: 🏛️
    title: Learn
    details: Understand how LensWord is put together and which surface fits your goal — architecture, design decisions, and the surface comparison.
    link: /learn/choose-a-surface
    linkText: Read the explanations
  - icon: 📚
    title: Reference
    details: Technical lookup material — ADRs, config/env vars, the changelog, release process, and what's actually been verified.
    link: /reference/verification
    linkText: Browse reference
  - icon: 🔍
    title: Trust & verification
    details: What's been tested and how, what hasn't, and every known gap — stated plainly.
    link: /reference/verification
    linkText: See what's verified
  - icon: 🤝
    title: Contributing & support
    details: Development setup, the pull request process, and how to sponsor the project.
    link: /contributing
    linkText: Contribute
---

## What LensWord is

LensWord is an open-source vocabulary trainer that forces spaced-repetition
recall instead of passive review, and lets you anchor words spatially in a
memory palace (the method of loci). It's a FastAPI + Postgres backend behind
a Vite/React web app, with an optional desktop shell, browser extension, and
MCP server for AI clients — see [Choose your surface](/learn/choose-a-surface) for what
each one is good for and how mature it is today.

<SurfaceChooser />

## How these docs are organized

This site follows the [Diátaxis](https://diataxis.fr/) framework, so each
page has one job:

- **[Setup](/setup/)** — a tutorial. Follow it once, end to end, to get LensWord running.
- **[Install](/install/web-app)** — how-to guides. Task-oriented recipes for a specific surface or problem.
- **[Learn](/learn/choose-a-surface)** — explanation. Understand how the pieces fit together and why.
- **[Reference](/reference/verification)** — lookup material. ADRs, config, the changelog, and what's verified.

No tagged release exists yet for any surface — this documentation describes
the current `development` branch, evaluated with evidence rather than
assumed. See [Trust & verification](/reference/verification) for the full picture.
