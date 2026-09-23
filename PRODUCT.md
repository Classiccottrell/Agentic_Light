# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Maintainers and contributors use the static microsite to scan repository health, inspect specialization presets, and understand which agent roles each preset activates.

## Product Purpose

Agentic Light is a lightweight, manually operated agent-workspace fork. The microsite makes its current operating state legible without requiring a framework, build step, or network-backed API.

## Operating Context

Pages are opened from a local checkout or served as static files. Health data is a checked-in `status.js` snapshot. Preset and roster content is generated from `System_Config/` source files.

## Capabilities and Constraints

- The dashboard is the primary home page.
- Health, presets, roster coverage, white-labeling guidance, and generated documentation remain available from static HTML.
- Pages must render over `file://` and remain usable with JavaScript unavailable where practical.
- The microsite must respect reduced-motion preferences and maintain accessible contrast and focus states.

## Brand Commitments

The product name is Agentic Light. The user requested a restrained Linefield-inspired generative background while keeping the microsite operational, readable, and lightweight.

## Evidence on Hand

The repository contains the agent roster, skills, presets, generated status snapshot, and the separate `Projects/linefield` generative-background library. No testimonials, customer claims, or external proof should be invented.

## Product Principles

- Operational state comes before explanation.
- Source files remain the authority; generated pages stay reproducible.
- Static delivery is a feature, not a limitation.
- Visual character must never compete with scanability.

## Accessibility & Inclusion

Target WCAG AA contrast, keyboard access, semantic landmarks, responsive layouts, and reduced-motion support.
