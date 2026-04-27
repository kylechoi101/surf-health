"use client";

import React, { useState, useEffect } from 'react';
import { LockupHorizontal } from "@/components/Lockup";

export default function StickyHeader() {
  const [isScrolled, setIsScrolled] = useState(false);

  useEffect(() => {
    const handleScroll = () => {
      setIsScrolled(window.scrollY > 40);
    };
    window.addEventListener('scroll', handleScroll);
    return () => window.removeEventListener('scroll', handleScroll);
  }, []);

  return (
    <header className={`site-header ${isScrolled ? 'scrolled' : ''}`} style={{
      position: 'sticky',
      top: 0,
      zIndex: 100,
      padding: isScrolled ? '10px 48px' : '20px 48px',
      backgroundColor: isScrolled ? 'rgba(250, 246, 238, 0.9)' : 'rgba(241, 234, 217, 0.85)',
      borderBottom: '1px solid var(--sl-line)',
      backdropFilter: 'blur(12px)',
      transition: 'all 0.4s cubic-bezier(0.2, 1, 0.3, 1)',
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'center',
    }}>
      <a href="/" className="brand-lockup" style={{ textDecoration: 'none' }}>
        <LockupHorizontal 
          size={isScrolled ? 22 : 28} 
          subtitle={isScrolled ? undefined : "California beach health forecasts"} 
        />
      </a>
      <nav className="site-nav" style={{ display: 'flex', gap: 8 }}>
        <NavLink href="/" active={true}>Forecast</NavLink>
        <NavLink href="/beaches">Stations</NavLink>
        <NavLink href="/research">Research</NavLink>
        <NavLink href="/methodology">Methodology</NavLink>
      </nav>
    </header>
  );
}

function NavLink({ href, children, active = false }: { href: string, children: React.ReactNode, active?: boolean }) {
  return (
    <a href={href} style={{
      fontFamily: 'var(--font-mono)',
      fontSize: 10,
      fontWeight: 600,
      textTransform: 'uppercase',
      letterSpacing: '0.12em',
      color: active ? 'var(--sl-navy)' : 'var(--sl-muted)',
      padding: '7px 14px',
      borderRadius: '999px',
      border: active ? '1px solid var(--sl-navy)' : '1px solid transparent',
      textDecoration: 'none',
      transition: 'all 0.2s ease',
    }}>
      {children}
    </a>
  );
}
