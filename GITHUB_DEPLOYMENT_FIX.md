# GitHub Actions Deployment Fix Journey

## The Problem
The web deployment to GitHub Pages (`deploy-web.yml`) was failing repeatedly due to several interconnected issues during the static export phase (`next build` with `output: export`):

1.  **Next.js 15 Breaking Changes:** Page parameters (`params` and `searchParams`) in Next.js 15 are now `Promises`. Components and `generateMetadata` functions were trying to access them synchronously, causing TypeScript errors.
2.  **Static Export vs. Dynamic Routes:** Dynamic routes like `/beaches/[id]` and `/b/[id]` did not implement `generateStaticParams`, which is mandatory for static HTML export.
3.  **Client/Server Component Conflict:** Combining `"use client"` with `generateStaticParams` or `generateMetadata` in the same file is not allowed.
4.  **Static Logic in Metadata:** The `opengraph-image.tsx` utility was using the `edge` runtime, which is incompatible with `dynamic = "force-static"` in a static export context.
5.  **Environment Discrepancies:** The CI runner was using Node.js 20, while the local successful builds were using Node.js 23.

## The Fixes

### 1. Architectural Refactoring
We split the dynamic pages into server-side entry points (`page.tsx`) and client-side implementation files (`BeachDetail.tsx`, `BeachSharePage.tsx`):
-   The server-side `page.tsx` handles `generateStaticParams` and `generateMetadata`.
-   The client-side files handle the interactive UI logic and state.

### 2. Next.js 15 Compatibility
We updated all dynamic routes to `await` the `params` object:
```typescript
export default async function Page(props: { params: Promise<{ id: string }> }) {
  const params = await props.params;
  // ...
}
```

### 3. Static Export Optimization
-   Implemented `generateStaticParams` for all dynamic routes, fetching the full list of station IDs from the production API.
-   Updated `web/lib/api.ts` to allow passing `cache: 'force-cache'` to `fetch` calls, satisfying the static data requirements of the export process.

### 4. OpenGraph Asset Automation
-   Fixed `opengraph-image.tsx` by removing the `edge` runtime and enforcing `export const dynamic = "force-static"`.
-   This allows the social preview images to be generated at build time and served as static assets.

### 5. CI Pipeline Alignment
-   Updated `.github/workflows/deploy-web.yml` to use **Node.js 23**.
-   Disabled the npm cache temporarily to ensure a clean build and prevent version conflicts.

## Result
The web deployment pipeline is now **green**. The Shorelife redesign is live at `https://kylechoi101.github.io/surf-health/` with fully functional maps, headers, and dynamic social metadata.
