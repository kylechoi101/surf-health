import React from 'react';
import Link from 'next/link';
import { EditorialPage } from '@/components/EditorialPage';

export default function PrivacyPage() {
  return (
    <EditorialPage>
      <article style={{ padding: '64px 64px 96px', maxWidth: 1280, margin: '0 auto' }}>
        <div style={{ marginBottom: 12 }}>
          <Link href="/" style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--sl-muted)', textDecoration: 'none', letterSpacing: '0.08em' }}>
            ← Home
          </Link>
        </div>

        <div style={{ color: 'var(--sl-sun-deep)', fontFamily: 'var(--font-mono)', fontSize: '0.85rem', textTransform: 'uppercase', letterSpacing: '0.12em' }}>
          Legal
        </div>
        <h1 style={{ fontFamily: 'var(--font-heading)', fontSize: 80, marginTop: 18, marginBottom: 32, fontWeight: 400, letterSpacing: '-0.02em', color: 'var(--sl-navy-ink)', maxWidth: 900, lineHeight: 1.1 }}>
          Privacy Policy
        </h1>
        
        <p style={{ fontFamily: 'var(--font-text)', fontSize: 20, color: 'var(--sl-ink)', lineHeight: 1.6, maxWidth: 680, margin: '0 0 40px' }}>
          Effective Date: April 28, 2026. This Privacy Policy describes how Shorelife 
          ("we", "our", or "us") collects, uses, and shares information when you use our 
          website and mobile application.
        </p>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 40, marginTop: 40, borderTop: '1px solid var(--sl-line)', paddingTop: 40 }}>
          <section>
            <h2 style={{ fontFamily: 'var(--font-heading)', fontSize: 28, color: 'var(--sl-navy)', marginBottom: 16, fontWeight: 400 }}>
              1. What data we collect
            </h2>
            <p style={{ fontFamily: 'var(--font-text)', fontSize: 16, color: 'var(--sl-ink)', lineHeight: 1.65, maxWidth: 680, margin: 0 }}>
              <strong>Location Data:</strong> When using the iOS application, we request access to your approximate location 
              to show nearby beaches. We only collect location data when you grant "While Using the App" permissions. 
              We do not track you in the background and we do not collect precise GPS coordinates.
              <br/><br/>
              <strong>User Identifiers:</strong> We do not require you to create an account, nor do we collect personally 
              identifiable information (PII) such as names, email addresses, or phone numbers.
            </p>
          </section>

          <section>
            <h2 style={{ fontFamily: 'var(--font-heading)', fontSize: 28, color: 'var(--sl-navy)', marginBottom: 16, fontWeight: 400 }}>
              2. What we send to third parties
            </h2>
            <p style={{ fontFamily: 'var(--font-text)', fontSize: 16, color: 'var(--sl-ink)', lineHeight: 1.65, maxWidth: 680, margin: 0 }}>
              <strong>Forecasting APIs:</strong> We send generalized location queries to weather and environmental APIs, 
              such as Open-Meteo and USGS NWIS, strictly for the purpose of generating coastal water quality forecasts.
              <br/><br/>
              <strong>No Advertising SDKs:</strong> There are currently no third-party advertising SDKs or tracking 
              analytics embedded in the Shorelife mobile application.
            </p>
          </section>

          <section>
            <h2 style={{ fontFamily: 'var(--font-heading)', fontSize: 28, color: 'var(--sl-navy)', marginBottom: 16, fontWeight: 400 }}>
              3. Children's Privacy
            </h2>
            <p style={{ fontFamily: 'var(--font-text)', fontSize: 16, color: 'var(--sl-ink)', lineHeight: 1.65, maxWidth: 680, margin: 0 }}>
              The Shorelife application is intended for a general audience. We do not knowingly collect, use, 
              or share information from children. If you believe we have inadvertently collected such information, 
              please contact us.
            </p>
          </section>

          <section>
            <h2 style={{ fontFamily: 'var(--font-heading)', fontSize: 28, color: 'var(--sl-navy)', marginBottom: 16, fontWeight: 400 }}>
              4. Contact Us
            </h2>
            <p style={{ fontFamily: 'var(--font-text)', fontSize: 16, color: 'var(--sl-ink)', lineHeight: 1.65, maxWidth: 680, margin: 0 }}>
              If you have any questions or concerns about this Privacy Policy, please reach out to us at 
              <a href="mailto:kylechoidsc@gmail.com" style={{ color: 'var(--sl-navy)', textDecoration: 'underline', marginLeft: 6 }}>kylechoidsc@gmail.com</a>.
            </p>
          </section>
        </div>
      </article>
    </EditorialPage>
  );
}