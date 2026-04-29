import React from 'react';
import Link from 'next/link';

export default function PrivacyPage() {
  return (
    <main className="min-h-screen bg-background pt-32 pb-24">
      <article className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="mb-4">
          <Link href="/" className="font-mono text-[11px] text-muted-foreground hover:text-foreground transition-colors tracking-widest">
            ← Home
          </Link>
        </div>

        <div className="text-primary text-sm tracking-widest uppercase font-medium mb-4">
          Legal
        </div>
        <h1 className="text-5xl md:text-7xl font-light mb-8 text-foreground text-balance">
          Privacy Policy
        </h1>
        
        <p className="text-xl text-muted-foreground leading-relaxed max-w-3xl mb-16">
          Effective Date: April 28, 2026. This Privacy Policy describes how Shorelife 
          ("we", "our", or "us") collects, uses, and shares information when you use our 
          website and mobile application.
        </p>

        <div className="space-y-16 mt-16 border-t border-border/50 pt-16">
          <section>
            <h2 className="text-3xl font-light mb-6 text-foreground">
              1. What data we collect
            </h2>
            <p className="text-base text-muted-foreground leading-relaxed max-w-2xl">
              <strong>Location Data:</strong> When using the iOS application, we request access to your approximate location 
              to show nearby beaches. We only collect location data when you grant "While Using the App" permissions. 
              We do not track you in the background and we do not collect precise GPS coordinates.
              <br/><br/>
              <strong>User Identifiers:</strong> We do not require you to create an account, nor do we collect personally 
              identifiable information (PII) such as names, email addresses, or phone numbers.
            </p>
          </section>

          <section>
            <h2 className="text-3xl font-light mb-6 text-foreground">
              2. What we send to third parties
            </h2>
            <p className="text-base text-muted-foreground leading-relaxed max-w-2xl">
              <strong>Forecasting APIs:</strong> We send generalized location queries to weather and environmental APIs, 
              such as Open-Meteo and USGS NWIS, strictly for the purpose of generating coastal water quality forecasts.
              <br/><br/>
              <strong>No Advertising SDKs:</strong> There are currently no third-party advertising SDKs or tracking 
              analytics embedded in the Shorelife mobile application.
            </p>
          </section>

          <section>
            <h2 className="text-3xl font-light mb-6 text-foreground">
              3. Children's Privacy
            </h2>
            <p className="text-base text-muted-foreground leading-relaxed max-w-2xl">
              The Shorelife application is intended for a general audience. We do not knowingly collect, use, 
              or share information from children. If you believe we have inadvertently collected such information, 
              please contact us.
            </p>
          </section>

          <section>
            <h2 className="text-3xl font-light mb-6 text-foreground">
              4. Contact Us
            </h2>
            <p className="text-base text-muted-foreground leading-relaxed max-w-2xl">
              If you have any questions or concerns about this Privacy Policy, please reach out to us at{' '}
              <a href="mailto:kylechoidsc@gmail.com" className="text-primary hover:underline font-medium">kylechoidsc@gmail.com</a>.
            </p>
          </section>
        </div>
      </article>
    </main>
  );
}