"use client";

import Link from "next/link";
import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { LockupHorizontal } from "@/components/Lockup";
import { Menu, X } from "lucide-react";

const navLinks = [
  { href: "/", label: "Forecast" },
  { href: "/beaches", label: "Stations" },
  { href: "/research", label: "Research" },
  { href: "/methodology", label: "Methodology" },
];

export function Header() {
  const [isMenuOpen, setIsMenuOpen] = useState(false);
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const handleScroll = () => setScrolled(window.scrollY > 20);
    window.addEventListener("scroll", handleScroll);
    return () => window.removeEventListener("scroll", handleScroll);
  }, []);

  return (
    <header 
      className={`fixed top-0 left-0 right-0 z-50 transition-all duration-300 border-b ${
        scrolled 
          ? "bg-navy py-3 border-navy shadow-lg" 
          : "bg-ecru/80 backdrop-blur-md py-5 border-border/30"
      }`}
    >
      <div className="max-w-[1600px] mx-auto px-6 md:px-16">
        <div className="flex items-center justify-between h-12">
          {/* Logo */}
          <Link href="/" className="flex items-center group">
            <LockupHorizontal 
              size={28} 
              subtitle="California" 
              ink={scrolled ? "var(--sl-bone)" : "var(--sl-navy)"} 
            />
          </Link>

          {/* Desktop Navigation */}
          <nav className="hidden lg:flex items-center gap-10">
            {navLinks.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                className={`sl-label text-[10px] transition-colors py-2 px-1 ${
                  scrolled
                    ? "text-bone/70 hover:text-bone"
                    : "text-muted-foreground hover:text-navy"
                }`}
              >
                {link.label}
              </Link>
            ))}
          </nav>

          {/* CTA Button */}
          <div className="hidden md:flex items-center gap-4">
            <Button 
              asChild 
              variant="outline"
              className={`sl-label text-[10px] border-2 h-10 px-6 rounded-full transition-all ${
                scrolled 
                  ? "border-bone text-bone hover:bg-bone hover:text-navy bg-transparent" 
                  : "border-navy text-navy hover:bg-navy hover:text-bone bg-transparent"
              }`}
            >
              <Link href="/beaches">Find a Beach</Link>
            </Button>
          </div>

          {/* Mobile Menu Button */}
          <button
            onClick={() => setIsMenuOpen(!isMenuOpen)}
            className={`lg:hidden p-2 transition-colors ${
              scrolled ? "text-bone" : "text-navy"
            }`}
            aria-label="Toggle menu"
          >
            {isMenuOpen ? <X size={24} /> : <Menu size={24} />}
          </button>
        </div>

        {/* Mobile Menu */}
        {isMenuOpen && (
          <div className="lg:hidden py-6 mt-4 border-t border-border/10">
            <nav className="flex flex-col gap-6">
              {navLinks.map((link) => (
                <Link
                  key={link.href}
                  href={link.href}
                  onClick={() => setIsMenuOpen(false)}
                  className={`sl-label text-sm ${
                    scrolled ? "text-bone" : "text-navy"
                  }`}
                >
                  {link.label}
                </Link>
              ))}
              <div className="pt-6 border-t border-border/10">
                <Button 
                  asChild 
                  className={`w-full h-12 sl-label rounded-xl ${
                    scrolled ? "bg-bone text-navy" : "bg-navy text-bone"
                  }`}
                >
                   <Link href="/beaches" onClick={() => setIsMenuOpen(false)}>Find a Beach</Link>
                </Button>
              </div>
            </nav>
          </div>
        )}
      </div>
    </header>
  );
}
