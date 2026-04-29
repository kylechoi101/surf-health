"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import type { BeachSummary } from "@/lib/api";
import { IconSearch, IconChevron, IconClose } from "../Icons";
import TabBar from "../TabBar";

const REGIONS = ["All", "SoCal", "Central", "NorCal"];
const REGION_LABELS: Record<string, string> = {
  SoCal: "Southern California",
  Central: "Central California",
  NorCal: "Northern California",
};

export default function SearchScreen({ beaches }: { beaches: BeachSummary[] }) {
  const [q, setQ] = useState("");
  const [region, setRegion] = useState("All");
  const router = useRouter();

  const uniqueBeaches = Array.from(new Map(beaches.map(b => [b.name, b])).values());
  const filtered = uniqueBeaches
    .filter((b) => region === "All" || b.region === region || b.region === REGION_LABELS[region])
    .filter(
      (b) =>
        !q ||
        b.name.toLowerCase().includes(q.toLowerCase()) ||
        b.county.toLowerCase().includes(q.toLowerCase())
    );

  const grouped: Record<string, BeachSummary[]> = {};
  filtered.forEach((b) => {
    (grouped[b.region] = grouped[b.region] ?? []).push(b);
  });
  const regionOrder = Object.keys(grouped).sort();

  return (
    <div className="sh-screen" style={{ background: "#f2f4f7" }}>
      {/* Sticky header */}
      <div style={{
        padding: "16px 20px 0", background: "#fff", borderBottom: "1px solid #e5e7eb",
        position: "sticky", top: 0, zIndex: 2,
      }}>
        <h1 style={{ fontSize: 22, fontWeight: 700, marginBottom: 12 }}>Browse beaches</h1>
        <div className="sh-search-box">
          <IconSearch />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder={`Search ${beaches.length}+ beaches`}
          />
          {q && (
            <button onClick={() => setQ("")}
              style={{ background: "none", border: "none", cursor: "pointer", color: "#94a3b8", padding: 0 }}>
              <IconClose />
            </button>
          )}
        </div>

        {/* Region filter pills */}
        <div style={{ display: "flex", gap: 6, margin: "12px 0", overflowX: "auto" }}>
          {REGIONS.map((r) => (
            <button key={r} onClick={() => setRegion(r)}
              style={{
                padding: "6px 12px", borderRadius: 999, whiteSpace: "nowrap",
                border: "1px solid " + (region === r ? "#0b4266" : "#e5e7eb"),
                background: region === r ? "#0b4266" : "#fff",
                color: region === r ? "#fff" : "#0f172a",
                fontSize: 12, fontWeight: 600, fontFamily: "inherit", cursor: "pointer",
              }}>
              {r}
            </button>
          ))}
        </div>
      </div>

      {/* Results */}
      {regionOrder.map((r) => (
        <div key={r} style={{ marginTop: 20 }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: "#64748b", letterSpacing: "0.08em",
            textTransform: "uppercase", padding: "0 20px", marginBottom: 8,
            display: "flex", justifyContent: "space-between" }}>
            <span>{REGION_LABELS[r] ?? r}</span>
            <span style={{ opacity: 0.6 }}>{grouped[r].length}</span>
          </div>
          <div style={{ padding: "0 20px", display: "flex", flexDirection: "column", gap: 8 }}>
            {grouped[r].map((b) => (
              <button key={b.id} onClick={() => router.push(`/m/beach/${b.id}`)}
                style={{ display: "flex", alignItems: "center", gap: 12, padding: 12,
                  background: "#fff", border: "1px solid #e5e7eb", borderRadius: 14,
                  cursor: "pointer", fontFamily: "inherit", textAlign: "left", width: "100%" }}>
                <span className="sh-dot" style={{ background: "#94a3b8" }}/>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 14, fontWeight: 600, color: "#0f172a" }}>{b.name}</div>
                  <div style={{ fontSize: 11, color: "#64748b", marginTop: 2 }}>{b.county} County</div>
                </div>
                <IconChevron />
              </button>
            ))}
          </div>
        </div>
      ))}

      {!filtered.length && (
        <div style={{ textAlign: "center", padding: "40px 20px", color: "#64748b" }}>
          <div style={{ fontSize: 15, fontWeight: 600 }}>No beaches match</div>
          <div style={{ fontSize: 13, marginTop: 4 }}>Try a different search or region.</div>
        </div>
      )}

      <TabBar />
    </div>
  );
}
