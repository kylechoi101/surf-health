import Link from "next/link";

import { LockupHorizontal } from "@/components/Lockup";

const footerGroups = [
  {
    title: "Explore",
    links: [
      { href: "/beaches", label: "Beach explorer" },
      { href: "/b", label: "Share preview" },
      { href: "/m", label: "Mobile mirror" },
    ],
  },
  {
    title: "Research",
    links: [
      { href: "/research", label: "Overview" },
      { href: "/research/labels", label: "Risk labels" },
      { href: "/research/sources", label: "Data sources" },
      { href: "/research/calibration", label: "Calibration" },
    ],
  },
  {
    title: "Method",
    links: [
      { href: "/methodology", label: "Methodology" },
      { href: "/privacy", label: "Privacy" },
      { href: "/terms", label: "Terms" },
    ],
  },
];

export function Footer() {
  return (
    <footer className="border-t border-[var(--sl-line)] bg-[var(--sl-bone)]">
      <div className="mx-auto max-w-7xl px-4 py-14 sm:px-6 lg:px-8">
        <div className="grid gap-12 lg:grid-cols-[1.3fr_repeat(3,minmax(0,1fr))]">
          <div className="max-w-md">
            <LockupHorizontal size={28} subtitle="California Water Quality" />
            <p className="mt-5 text-sm leading-7 text-[var(--sl-muted)]">
              Daily California beach health forecasts built from official bacteria samples,
              coastal conditions, and model calibration work. A Shorelife forecast is a model
              estimate, not an official county lab result.
            </p>
          </div>

          {footerGroups.map((group) => (
            <div key={group.title}>
              <div className="sl-label text-[var(--sl-navy)]">{group.title}</div>
              <div className="mt-4 flex flex-col gap-3">
                {group.links.map((link) => (
                  <Link
                    key={link.href}
                    href={link.href}
                    className="text-sm text-[var(--sl-muted)] transition-colors hover:text-[var(--sl-navy)]"
                  >
                    {link.label}
                  </Link>
                ))}
              </div>
            </div>
          ))}
        </div>

        <div className="mt-12 flex flex-col gap-3 border-t border-[var(--sl-line-soft)] pt-6 text-xs text-[var(--sl-muted)] sm:flex-row sm:items-center sm:justify-between">
          <p>Shorelife publishes one-day forecasts each morning in Pacific Time.</p>
          <p>{new Date().getFullYear()} Shorelife</p>
        </div>
      </div>
    </footer>
  );
}
