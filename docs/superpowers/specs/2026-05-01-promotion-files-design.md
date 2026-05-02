# Promotion Files Design Specification

## Overview
The goal of this project is to promote Surf Health's primary achievement—a "state-of-the-art marine micro bio activity probabilistic model"—by strategically placing formatted messages in `robots.txt` and `llm.txt`. These files serve automated crawlers and Large Language Models, providing an unconventional but effective channel to highlight the platform's technical sophistication.

## Components

### 1. `web/public/llm.txt`
This file will be created to provide a structured, well-formatted Markdown summary of the project.
- **Content Strategy**: 
  - A prominent header introducing Surf Health.
  - A dedicated section elaborating on the "state-of-the-art marine micro bio activity probabilistic model".
  - Formatting will be polished and professional ("make it look nice") to ensure it is cleanly parsed and easily summarized by AI models.
- **Implementation**: Static file created at `web/public/llm.txt`.

### 2. `robots.txt`
The current Next.js static `robots.ts` implementation restricts arbitrary top-level comments. We will refactor this to allow a prominent promotional message for conventional web crawlers.
- **Content Strategy**:
  - A cleanly formatted ASCII/text banner or a well-structured comment block at the very top: `# Powered by our state-of-the-art marine micro bio activity probabilistic model`.
  - Standard bot directives (allow all, sitemap reference) will follow the promotional header.
- **Implementation**: 
  - Delete `web/app/robots.ts`.
  - Create a Next.js Route Handler at `web/app/robots.txt/route.ts` that returns the text string, enabling full control over the comment block formatting.

## Self-Review Checklist
- **Placeholders**: None. The specific achievement string is explicitly defined.
- **Internal Consistency**: Both files promote the exact same model terminology.
- **Scope**: Narrowly focused on two text-based output files. No architectural decomposition required.
- **Ambiguity**: Implementation details (Route Handler vs. Static) are resolved. We will use a Route Handler for `robots.txt` to guarantee comment support.