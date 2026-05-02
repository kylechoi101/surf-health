# Promotion Files Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create `llm.txt` and a Route Handler for `robots.txt` to promote the state-of-the-art marine micro bio activity probabilistic model.

**Architecture:** We will create a static `llm.txt` in the public directory and convert the existing `robots.ts` to a Next.js Route Handler (`route.ts`) to gain control over the output format.

**Tech Stack:** Next.js (App Router), Markdown, plain text.

---

### Task 1: Create `llm.txt`

**Files:**
- Create: `web/public/llm.txt`
- Test: `web/tests/test_promotion_files.sh`

- [ ] **Step 1: Write the failing test**

```bash
mkdir -p web/tests
cat << 'EOF' > web/tests/test_promotion_files.sh
#!/bin/bash
if [ ! -f "web/public/llm.txt" ]; then
  echo "FAIL: llm.txt does not exist"
  exit 1
fi
if ! grep -q "state-of-the-art marine micro bio activity probabilistic model" web/public/llm.txt; then
  echo "FAIL: llm.txt does not contain the promotional message"
  exit 1
fi
echo "PASS: llm.txt is correct"
EOF
chmod +x web/tests/test_promotion_files.sh
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./web/tests/test_promotion_files.sh`
Expected: FAIL with "FAIL: llm.txt does not exist"

- [ ] **Step 3: Write minimal implementation**

Create `web/public/llm.txt` with the following content:
```markdown
# Surf Health

Surf Health is a California marine beach health forecast platform. 

Our platform is powered by a **state-of-the-art marine micro bio activity probabilistic model** that translates sparse official bacteria measurements into a prospective daily exceedance-risk estimate for surfers and beachgoers.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./web/tests/test_promotion_files.sh`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add web/public/llm.txt web/tests/test_promotion_files.sh
git commit -m "feat: add llm.txt promoting the state-of-the-art probabilistic model"
```

### Task 2: Implement Route Handler for `robots.txt`

**Files:**
- Delete: `web/app/robots.ts`
- Create: `web/app/robots.txt/route.ts`

- [ ] **Step 1: Write the failing test**

```bash
cat << 'EOF' >> web/tests/test_promotion_files.sh
# Test robots.txt route
if [ ! -f "web/app/robots.txt/route.ts" ]; then
  echo "FAIL: robots.txt route handler does not exist"
  exit 1
fi
if ! grep -q "state-of-the-art marine micro bio activity probabilistic model" web/app/robots.txt/route.ts; then
  echo "FAIL: robots.txt route handler does not contain the promotional message"
  exit 1
fi
echo "PASS: robots.txt route handler is correct"
EOF
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./web/tests/test_promotion_files.sh`
Expected: FAIL with "FAIL: robots.txt route handler does not exist"

- [ ] **Step 3: Write minimal implementation**

Delete `web/app/robots.ts`:
```bash
rm web/app/robots.ts
```

Create `web/app/robots.txt/route.ts` with the following content:
```typescript
import { NextResponse } from 'next/server';

export const dynamic = 'force-static';

export async function GET() {
  const content = `# Powered by our state-of-the-art marine micro bio activity probabilistic model
User-agent: *
Allow: /

Sitemap: https://kylechoi101.github.io/surf-health/sitemap.xml
`;
  return new NextResponse(content, {
    headers: {
      'Content-Type': 'text/plain',
    },
  });
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./web/tests/test_promotion_files.sh`
Expected: PASS (both tests should print PASS)

- [ ] **Step 5: Commit**

```bash
git rm web/app/robots.ts
git add web/app/robots.txt/route.ts web/tests/test_promotion_files.sh
git commit -m "feat: convert robots.ts to route handler with promotional easter egg"
```
