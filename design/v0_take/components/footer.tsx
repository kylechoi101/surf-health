"use client";

import Link from "next/link";
import { ShoreLifeLogo } from "@/components/shorelife-logo";

const footerLinks = {
  platform: [
    { label: "Research Areas", href: "#research" },
    { label: "Coastal Map", href: "#map" },
    { label: "Artifacts", href: "#artifacts" },
    { label: "API Access", href: "#" },
  ],
  resources: [
    { label: "Documentation", href: "#" },
    { label: "Methodology Guide", href: "#" },
    { label: "Data Standards", href: "#" },
    { label: "Publications", href: "#" },
  ],
  organization: [
    { label: "About Us", href: "#about" },
    { label: "Research Partners", href: "#" },
    { label: "Careers", href: "#" },
    { label: "Contact", href: "#" },
  ],
  legal: [
    { label: "Privacy Policy", href: "#" },
    { label: "Terms of Use", href: "#" },
    { label: "Data License", href: "#" },
  ],
};

export function Footer() {
  return (
    <footer id="about" className="bg-foreground text-background relative">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-16">
        <div className="grid md:grid-cols-2 lg:grid-cols-6 gap-12 mb-12">
          {/* Brand */}
          <div className="lg:col-span-2">
            <Link href="/" className="flex items-center gap-3 mb-6">
              <ShoreLifeLogo size={40} />
              <span className="text-xl font-light tracking-wide text-background">
                Shore<span className="font-semibold text-primary">Life</span>
              </span>
            </Link>
            <p className="text-background/60 mb-6 leading-relaxed max-w-sm text-sm">
              Real-time water quality monitoring and bacterial forecasting 
              for California&apos;s coastline. Serving researchers and public health.
            </p>
          </div>

          {/* Links */}
          <div>
            <h4 className="font-medium text-background text-sm tracking-wide mb-4">Platform</h4>
            <ul className="space-y-3">
              {footerLinks.platform.map((link) => (
                <li key={link.label}>
                  <Link
                    href={link.href}
                    className="text-background/60 hover:text-background transition-colors text-sm"
                  >
                    {link.label}
                  </Link>
                </li>
              ))}
            </ul>
          </div>

          <div>
            <h4 className="font-medium text-background text-sm tracking-wide mb-4">Resources</h4>
            <ul className="space-y-3">
              {footerLinks.resources.map((link) => (
                <li key={link.label}>
                  <Link
                    href={link.href}
                    className="text-background/60 hover:text-background transition-colors text-sm"
                  >
                    {link.label}
                  </Link>
                </li>
              ))}
            </ul>
          </div>

          <div>
            <h4 className="font-medium text-background text-sm tracking-wide mb-4">Organization</h4>
            <ul className="space-y-3">
              {footerLinks.organization.map((link) => (
                <li key={link.label}>
                  <Link
                    href={link.href}
                    className="text-background/60 hover:text-background transition-colors text-sm"
                  >
                    {link.label}
                  </Link>
                </li>
              ))}
            </ul>
          </div>

          <div>
            <h4 className="font-medium text-background text-sm tracking-wide mb-4">Legal</h4>
            <ul className="space-y-3">
              {footerLinks.legal.map((link) => (
                <li key={link.label}>
                  <Link
                    href={link.href}
                    className="text-background/60 hover:text-background transition-colors text-sm"
                  >
                    {link.label}
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        </div>

        {/* Bottom bar */}
        <div className="pt-8 border-t border-background/10 flex flex-col md:flex-row items-center justify-between gap-4">
          <p className="text-background/40 text-sm">
            {new Date().getFullYear()} ShoreLife Research Platform. All rights reserved.
          </p>
          <p className="text-background/40 text-sm">
            California coastal water quality monitoring
          </p>
        </div>
      </div>
    </footer>
  );
}
