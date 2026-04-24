"use client";

import { BeachSummary } from "@/lib/api";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { RiskBadge } from "./RiskBadge";

const FAVORITES_KEY = "surf-health-favorites";

export function BeachExplorer({
  beaches,
  risks
}: {
  beaches: BeachSummary[];
  risks: Record<string, "Low" | "Moderate" | "High" | "Very High">;
}) {
  const [favorites, setFavorites] = useState<string[]>([]);
  const [countyFilter, setCountyFilter] = useState<string>("All");
  const [showFavorites, setShowFavorites] = useState(false);

  useEffect(() => {
    const raw = window.localStorage.getItem(FAVORITES_KEY);
    if (raw) {
      setFavorites(JSON.parse(raw));
    }
  }, []);

  useEffect(() => {
    window.localStorage.setItem(FAVORITES_KEY, JSON.stringify(favorites));
  }, [favorites]);

  const counties = useMemo(
    () => ["All", ...Array.from(new Set(beaches.map((beach) => beach.county))).sort()],
    [beaches]
  );

  const filtered = beaches.filter((beach) => {
    if (countyFilter !== "All" && beach.county !== countyFilter) return false;
    if (showFavorites && !favorites.includes(beach.id)) return false;
    return true;
  });

  function toggleFavorite(beachId: string) {
    setFavorites((current) =>
      current.includes(beachId) ? current.filter((id) => id !== beachId) : [...current, beachId]
    );
  }

  return (
    <section className="panel">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Public App Surface</p>
          <h2>Daily risk explorer</h2>
        </div>
        <div className="filter-row">
          <select value={countyFilter} onChange={(event) => setCountyFilter(event.target.value)}>
            {counties.map((county) => (
              <option key={county} value={county}>
                {county}
              </option>
            ))}
          </select>
          <button className="ghost-button" onClick={() => setShowFavorites((value) => !value)}>
            {showFavorites ? "Show all" : "Favorites only"}
          </button>
        </div>
      </div>
      <div className="beach-grid">
        {filtered.map((beach) => (
          <article key={beach.id} className="beach-card">
            <div className="card-topline">
              <span>{beach.county}</span>
              <button className="favorite-button" onClick={() => toggleFavorite(beach.id)}>
                {favorites.includes(beach.id) ? "Saved" : "Save"}
              </button>
            </div>
            <h3>{beach.name}</h3>
            <p className="muted">
              {beach.region} • {beach.support_status}
            </p>
            <div className="card-footer">
              <RiskBadge band={risks[beach.id] ?? "Moderate"} />
              <Link href={`/beaches/${beach.id}`} className="pill-link">
                View details
              </Link>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

