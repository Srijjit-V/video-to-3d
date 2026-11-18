# ADR-0005: Front-end stack: keep static ES modules and CSS tokens for now; React, Vite, TypeScript and Tailwind proposed

**Date**: 2026-11-18
**Status**: proposed
**Deciders**: Srijjit (owner), Claude Code (implementation)

## Context

The viewer is a no-build static site (plain ES modules, one stylesheet, a strict CSP, 53 Node tests and 16 browser tests). The owner recommends Vite, React, TypeScript and Tailwind so it can share tokens and components with Intern Break (React 19, TypeScript, Express). The viewer's core is a three.js scene and the measuring code is already TypeScript.

## Decision

For now we keep the static stack and adopt Intern Break's design tokens in `viewer/css` (DESIGN.md). A migration to Vite + React + Tailwind is proposed, not done: it would rewrite about 900 lines of page logic and its 16 browser tests, and add a build step to Vercel and Pages. It needs the owner's decision.

## Alternatives Considered

### Alternative 1: Migrate now
- **Pros**: Shared components with Intern Break
- **Cons**: Large rewrite, a build step, new risk to a tested app, no new capability
- **Why not**: Cost now, benefit later.

### Alternative 2: Stay static forever
- **Pros**: No build
- **Cons**: No shared components
- **Why not**: Tokens can still be shared.

## Consequences

Design language is shared today through tokens; the app keeps working and tested.

### Risks

- The longer the static stack grows, the larger a later migration.
