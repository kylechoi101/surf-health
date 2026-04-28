"use client";

import React, { useEffect, useState, useMemo } from 'react';
import { getBeaches, preferredForecastDate, type BeachSummary } from '@/lib/api';
import { RiskChip, RISK_TOKEN } from '@/components/RiskComponents';

export default function BeachesDirectoryPage() {
  const [beaches, setBeaches] = useState<BeachSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [selectedCounty, setSelectedCounty] = useState("All");

  useEffect(() => {
    getBeaches().then(setBeaches).finally(() => setLoading(false));
  }, []);

  const counties = useMemo(() => {
    const set = new Set(beaches.map(b => b.county));
    return ["All", ...Array.from(set).sort()];
  }, [beaches]);

  const filtered = useMemo(() => {
    return beaches.filter(b => {
      const matchesSearch = b.name.toLowerCase().includes(search.toLowerCase()) || 
                           b.county.toLowerCase().includes(search.toLowerCase());
      const matchesCounty = selectedCounty === "All" || b.county === selectedCounty;
      return matchesSearch && matchesCounty;
    });
  }, [beaches, search, selectedCounty]);

  return (
    <main style={{ padding: '48px 64px 96px', maxWidth: 1200, margin: '0 auto' }}>
      <div style={{ color: 'var(--sl-sun-deep)', fontFamily: 'var(--font-mono)', fontSize: '0.85rem', textTransform: 'uppercase', letterSpacing: '0.12em' }}>
        Directory · {beaches.length} Stations
      </div>
      <h1 style={{ fontFamily: 'var(--font-heading)', fontSize: 72, marginTop: 18, marginBottom: 48, fontWeight: 400, letterSpacing: '-0.02em', color: 'var(--sl-navy-ink)' }}>
        California Beaches
      </h1>

      <div style={{ display: 'flex', gap: 16, marginBottom: 40 }}>
        <input 
          type="text" 
          placeholder="Search by name or county..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={{
            flex: 1,
            padding: '14px 20px',
            borderRadius: 12,
            border: '1px solid var(--sl-line)',
            background: 'var(--sl-bone)',
            fontFamily: 'var(--font-text)',
            fontSize: 16,
            outline: 'none',
            color: 'var(--sl-ink)',
          }}
        />
        <select 
          value={selectedCounty}
          onChange={(e) => setSelectedCounty(e.target.value)}
          style={{
            padding: '0 20px',
            borderRadius: 12,
            border: '1px solid var(--sl-line)',
            background: 'var(--sl-bone)',
            fontFamily: 'var(--font-mono)',
            fontSize: 12,
            textTransform: 'uppercase',
            letterSpacing: '0.05em',
            outline: 'none',
            color: 'var(--sl-ink)',
          }}
        >
          {counties.map(c => <option key={c} value={c}>{c}</option>)}
        </select>
      </div>

      {loading ? (
        <div style={{ color: 'var(--sl-muted)', fontFamily: 'var(--font-mono)' }}>Loading stations...</div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: 16 }}>
          {filtered.map(b => (
            <a 
              key={b.id} 
              href={`/beaches/${b.id}/`}
              style={{
                textDecoration: 'none',
                display: 'block',
                padding: '20px',
                background: 'var(--sl-bone)',
                border: '1px solid var(--sl-line)',
                borderRadius: 14,
                transition: 'all 0.2s ease',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.borderColor = 'var(--sl-navy)';
                e.currentTarget.style.transform = 'translateY(-2px)';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.borderColor = 'var(--sl-line)';
                e.currentTarget.style.transform = 'translateY(0)';
              }}
            >
              <div style={{ color: 'var(--sl-muted)', fontFamily: 'var(--font-mono)', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.1em' }}>
                {b.county} County
              </div>
              <h3 style={{ fontFamily: 'var(--font-heading)', fontSize: 20, margin: '8px 0 12px', color: 'var(--sl-navy-ink)', fontWeight: 400 }}>
                {b.name}
              </h3>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontSize: 12, color: 'var(--sl-muted)', fontFamily: 'var(--font-text)' }}>
                  {b.region}
                </span>
                <span style={{ fontSize: 18, color: 'var(--sl-line)' }}>→</span>
              </div>
            </a>
          ))}
        </div>
      )}

      {!loading && filtered.length === 0 && (
        <div style={{ padding: '64px', textAlign: 'center', color: 'var(--sl-muted)' }}>
          No beaches found matching "{search}" in {selectedCounty}.
        </div>
      )}
    </main>
  );
}
