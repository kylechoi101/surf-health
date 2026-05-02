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
