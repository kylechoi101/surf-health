"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { Menu, X } from "lucide-react";

import { LockupHorizontal } from "@/components/Lockup";
import { cn } from "@/lib/utils";

const navLinks = [
  { href: "/beaches", label: "Beaches" },
  { href: "/research", label: "Research" },
  { href: "/methodology", label: "Methodology" },
  { href: "/privacy", label: "Privacy" },
  { href: "/terms", label: "Terms" },
];

function isActive(pathname: string, href: string) {
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function Header() {
  const pathname = usePathname();
  const [isMenuOpen, setIsMenuOpen] = useState(false);

  return (
    <header className="sticky top-0 z-50 border-b border-[var(--sl-line)] bg-[rgba(241,234,217,0.9)] backdrop-blur-xl">
      <div className="mx-auto flex max-w-7xl items-center justify-between gap-6 px-4 py-4 sm:px-6 lg:px-8">
        <Link href="/" className="shrink-0">
          <LockupHorizontal size={26} subtitle="California Water Quality" />
        </Link>

        <nav className="hidden items-center gap-6 lg:flex">
          {navLinks.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className={cn(
                "sl-label border-b pb-1 transition-colors",
                isActive(pathname, link.href)
                  ? "border-[var(--sl-navy)] text-[var(--sl-navy)]"
                  : "border-transparent text-[var(--sl-muted)] hover:text-[var(--sl-navy)]"
              )}
            >
              {link.label}
            </Link>
          ))}
        </nav>

        <div className="hidden lg:block">
          <Link
            href="/beaches"
            className="sl-label inline-flex items-center rounded-full bg-[var(--sl-navy)] px-4 py-2 text-[var(--sl-bone)] transition-transform hover:-translate-y-0.5"
          >
            Open Explorer
          </Link>
        </div>

        <button
          type="button"
          onClick={() => setIsMenuOpen((open) => !open)}
          className="rounded-full border border-[var(--sl-line)] bg-[var(--sl-bone)] p-2 text-[var(--sl-navy)] lg:hidden"
          aria-label="Toggle navigation"
        >
          {isMenuOpen ? <X size={18} /> : <Menu size={18} />}
        </button>
      </div>

      {isMenuOpen && (
        <div className="border-t border-[var(--sl-line)] bg-[var(--sl-bone)] lg:hidden">
          <nav className="mx-auto flex max-w-7xl flex-col gap-1 px-4 py-4 sm:px-6">
            {navLinks.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                onClick={() => setIsMenuOpen(false)}
                className={cn(
                  "rounded-2xl px-4 py-3 text-sm transition-colors",
                  isActive(pathname, link.href)
                    ? "bg-[var(--sl-ecru-deep)] text-[var(--sl-navy)]"
                    : "text-[var(--sl-muted)] hover:bg-[var(--sl-ecru-deep)] hover:text-[var(--sl-navy)]"
                )}
              >
                {link.label}
              </Link>
            ))}
            <Link
              href="/beaches"
              onClick={() => setIsMenuOpen(false)}
              className="sl-label mt-3 inline-flex justify-center rounded-full bg-[var(--sl-navy)] px-4 py-3 text-[var(--sl-bone)]"
            >
              Open Explorer
            </Link>
          </nav>
        </div>
      )}
    </header>
  );
}
