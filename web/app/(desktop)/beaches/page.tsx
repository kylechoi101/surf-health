"use client";

import React, { useEffect, useState, useMemo } from 'react';
import Link from 'next/link';
import { getBeaches, type BeachSummary } from '@/lib/api';

export default function BeachesDirectoryPage() {
  const [beaches, setBeaches] = useState<BeachSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [selectedCounty, setSelectedCounty] = useState("All");

  useEffect(() => {
    getBeaches().then(setBeaches).finally(() => setLoading(false));
  }, []);

  const counties = useMemo(() => {
    const supportedBeaches = beaches.filter(b => b.support_status !== "unsupported");
    const set = new Set(supportedBeaches.map(b => b.county));
    return ["All", ...Array.from(set).sort()];
  }, [beaches]);

  const filtered = useMemo(() => {
    return beaches.filter(b => {
      if (b.support_status === "unsupported") return false;
      const matchesSearch = b.name.toLowerCase().includes(search.toLowerCase()) || 
                           b.county.toLowerCase().includes(search.toLowerCase());
      const matchesCounty = selectedCounty === "All" || b.county === selectedCounty;
      return matchesSearch && matchesCounty;
    });
  }, [beaches, search, selectedCounty]);

  return (
    <main className="min-h-screen bg-background pt-32 pb-24">
      <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="text-primary text-sm tracking-widest uppercase font-medium mb-4">
          Directory · {filtered.length} Stations
        </div>
        <h1 className="text-5xl md:text-7xl font-light mb-12 text-foreground">
          California Beaches
        </h1>

        <div className="flex flex-col sm:flex-row gap-4 mb-16">
          <input 
            type="text" 
            placeholder="Search by name or county..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="flex-1 px-6 py-4 rounded-2xl border border-border/50 bg-muted/30 text-base text-foreground focus:outline-none focus:border-primary/50 transition-colors"
          />
          <select 
            value={selectedCounty}
            onChange={(e) => setSelectedCounty(e.target.value)}
            className="px-6 py-4 rounded-2xl border border-border/50 bg-muted/30 font-mono text-xs uppercase tracking-widest text-foreground focus:outline-none focus:border-primary/50 transition-colors appearance-none min-w-[200px]"
          >
            {counties.map(c => <option key={c} value={c}>{c}</option>)}
          </select>
        </div>

        {loading ? (
          <div className="font-mono text-sm text-muted-foreground animate-pulse">Loading stations...</div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {filtered.map(b => (
              <Link 
                key={b.id} 
                href={`/beaches/${b.id}/`}
                className="block p-6 bg-muted/30 border border-border/50 rounded-2xl hover:border-primary hover:-translate-y-1 transition-all duration-300 group"
              >
                <div className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground mb-3">
                  {b.county} County
                </div>
                <h3 className="text-xl font-medium text-foreground mb-4 line-clamp-1 group-hover:text-primary transition-colors">
                  {b.name}
                </h3>
                <div className="flex justify-between items-center mt-auto">
                  <span className="text-sm text-muted-foreground">
                    {b.region}
                  </span>
                  <span className="text-muted-foreground group-hover:text-primary transition-colors group-hover:translate-x-1">→</span>
                </div>
              </Link>
            ))}
          </div>
        )}

        {!loading && filtered.length === 0 && (
          <div className="py-24 text-center text-muted-foreground text-lg">
            No beaches found matching "{search}" in {selectedCounty}.
          </div>
        )}
      </div>
    </main>
  );
}
