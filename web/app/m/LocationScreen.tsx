"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import type { BeachSummary } from "@/lib/api";
import { IconSearch, IconLocate, IconChevron, IconClose } from "./Icons";

export default function LocationScreen({ beaches }: { beaches: BeachSummary[] }) {
  const [q, setQ] = useState("");
  const router = useRouter();

  const results = q
    ? beaches
        .filter(
          (b) =>
            b.name.toLowerCase().includes(q.toLowerCase()) ||
            b.county.toLowerCase().includes(q.toLowerCase())
        )
        .slice(0, 10)
    : [];

  function pick(b: BeachSummary) {
    router.push(`/m/beach/${b.id}`);
  }

  return (
    <div style={{
      height: "100dvh", display: "flex", flexDirection: "column",
      background: "linear-gradient(180deg, #0b4266 0%, #15719e 45%, #4da3c9 100%)",
      color: "#fff", position: "relative", overflow: "hidden",
    }}>
      {/* Ambient bg */}
      <svg viewBox="0 0 400 700" preserveAspectRatio="none"
        style={{ position: "absolute", inset: 0, width: "100%", height: "100%", opacity: 0.4, pointerEvents: "none" }}>
        <path d="M0 420 C 80 400, 160 460, 240 430 S 400 410, 400 430 L400 700 L0 700 Z" fill="#f4e5b9"/>
        <path d="M0 400 C 80 380, 160 440, 240 410 S 400 390, 400 410" stroke="#fff" strokeWidth="1" opacity="0.5" fill="none"/>
        <circle cx="320" cy="120" r="50" fill="#ffd97a" opacity="0.85"/>
      </svg>

      <div style={{ position: "relative", padding: "16px 22px 0", zIndex: 2 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 24 }}>
          <div style={{ width: 34, height: 34, borderRadius: 10, background: "rgba(255,255,255,0.22)",
            display: "flex", alignItems: "center", justifyContent: "center" }}>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
              <path d="M2 14c2.5 0 2.5-2 5-2s2.5 2 5 2 2.5-2 5-2 2.5 2 5 2M2 18c2.5 0 2.5-2 5-2s2.5 2 5 2 2.5-2 5-2 2.5 2 5 2"
                stroke="#fff" strokeWidth="2" strokeLinecap="round"/>
            </svg>
          </div>
          <span style={{ fontSize: 13, fontWeight: 700, letterSpacing: "0.08em", textTransform: "uppercase" }}>
            Surf Health
          </span>
        </div>
        <h1 style={{ fontSize: 36, fontWeight: 700, lineHeight: 1.05, marginTop: 36, maxWidth: 300 }}>
          Find out if the water&rsquo;s clean
          <span style={{ opacity: 0.7 }}>—before you paddle out.</span>
        </h1>
        <p style={{ fontSize: 15, opacity: 0.82, marginTop: 14, lineHeight: 1.5, maxWidth: 300 }}>
          Daily bacteria + surf forecast for 290+ California beaches.
        </p>
      </div>

      {/* Bottom sheet */}
      <div style={{
        marginTop: "auto", background: "#fff", color: "#0f172a",
        borderRadius: "28px 28px 0 0", padding: "22px 20px 32px", zIndex: 3,
        boxShadow: "0 -20px 60px rgba(0,0,0,0.2)",
      }}>
        {/* Search */}
        <div className="sh-search-box">
          <IconSearch />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search beaches, cities, counties"
          />
          {q && (
            <button onClick={() => setQ("")}
              style={{ background: "none", border: "none", cursor: "pointer", color: "#94a3b8", padding: 0 }}>
              <IconClose />
            </button>
          )}
        </div>

        {q ? (
          <div style={{ marginTop: 14, maxHeight: 240, overflowY: "auto" }}>
            {results.map((b) => (
              <button key={b.id} onClick={() => pick(b)}
                style={{ width: "100%", display: "flex", alignItems: "center", gap: 12,
                  padding: "10px 4px", border: "none", borderBottom: "1px solid #f1f5f9",
                  background: "none", cursor: "pointer", fontFamily: "inherit", textAlign: "left" }}>
                <span className="sh-dot" style={{ background: "#94a3b8" }}/>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 14, fontWeight: 600, color: "#0f172a" }}>{b.name}</div>
                  <div style={{ fontSize: 11, color: "#64748b", marginTop: 2 }}>{b.county} County · {b.region}</div>
                </div>
                <IconChevron />
              </button>
            ))}
            {!results.length && (
              <p style={{ fontSize: 13, color: "#64748b", padding: "12px 4px" }}>
                No matches — try another search.
              </p>
            )}
          </div>
        ) : (
          <div style={{ marginTop: 18 }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: "#64748b",
              textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 8 }}>
              Nearby beaches
            </div>
            {beaches.slice(0, 4).map((b) => (
              <button key={b.id} onClick={() => pick(b)}
                style={{ width: "100%", display: "flex", alignItems: "center", gap: 12,
                  padding: "11px 4px", border: "none", borderBottom: "1px solid #f8fafc",
                  background: "none", cursor: "pointer", fontFamily: "inherit", textAlign: "left" }}>
                <span className="sh-dot" style={{ background: "#94a3b8" }}/>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 14, fontWeight: 600, color: "#0f172a" }}>{b.name}</div>
                  <div style={{ fontSize: 11, color: "#64748b", marginTop: 2 }}>{b.county} County</div>
                </div>
                <IconChevron />
              </button>
            ))}
            <button
              onClick={() => router.push("/m/search")}
              style={{ width: "100%", marginTop: 14, padding: 12,
                border: "1px solid #e2e8f0", borderRadius: 12,
                background: "#fff", color: "#0b4266", fontWeight: 600,
                fontFamily: "inherit", fontSize: 14, cursor: "pointer" }}>
              Browse all beaches →
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
