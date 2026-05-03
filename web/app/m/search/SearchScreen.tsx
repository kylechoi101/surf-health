"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import type { BeachSummary } from "@/lib/api";
import { IconSearch, IconChevron, IconClose } from "../Icons";
import TabBar from "../TabBar";
import { getRegionGroup, regionLabel } from "../utils";

const REGIONS = ["All", "SoCal", "Central", "NorCal"];

export default function SearchScreen({ beaches }: { beaches: BeachSummary[] }) {
  const [q, setQ] = useState("");
  const [region, setRegion] = useState("All");
  const router = useRouter();

  const uniqueBeaches = Array.from(new Map(beaches.map(b => [b.name, b])).values());
  const filtered = uniqueBeaches
    .filter((b) => region === "All" || getRegionGroup(b.region) === region)
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
    <div className="min-h-[100dvh] pb-[calc(80px+env(safe-area-inset-bottom))] bg-muted/20 text-foreground overflow-y-auto">
      {/* Sticky header */}
      <div className="sticky top-0 z-10 px-5 pt-4 bg-background/95 backdrop-blur-md border-b border-border/50">
        <h1 className="text-[22px] font-bold mb-3">Browse beaches</h1>
        <div className="flex items-center gap-2.5 bg-muted/50 rounded-2xl p-3 border border-border/50 focus-within:border-primary transition-colors">
          <IconSearch />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder={`Search ${beaches.length}+ beaches`}
            className="flex-1 bg-transparent border-none outline-none text-[15px] text-foreground placeholder:text-muted-foreground"
          />
          {q && (
            <button onClick={() => setQ("")} className="text-muted-foreground p-1 hover:text-foreground">
              <IconClose />
            </button>
          )}
        </div>

        {/* Region filter pills */}
        <div className="flex gap-1.5 my-3 overflow-x-auto no-scrollbar">
          {REGIONS.map((r) => (
            <button key={r} onClick={() => setRegion(r)}
              className={`px-3 py-1.5 rounded-full whitespace-nowrap text-xs font-semibold tracking-wide border transition-colors ${
                region === r 
                  ? "border-primary bg-primary text-primary-foreground" 
                  : "border-border/50 bg-background text-foreground hover:bg-muted/50"
              }`}>
              {r}
            </button>
          ))}
        </div>
      </div>

      {/* Results */}
      <div className="py-2">
        {regionOrder.map((r) => (
          <div key={r} className="mt-5">
            <div className="text-[11px] font-bold text-muted-foreground tracking-widest uppercase px-5 mb-2 flex justify-between">
              <span>{regionLabel(r)}</span>
              <span className="opacity-60">{grouped[r].length}</span>
            </div>
            <div className="px-4 flex flex-col gap-2">
              {grouped[r].map((b) => (
                <button key={b.id} onClick={() => router.push(`/m/beach/${b.id}`)}
                  className="flex items-center gap-3 p-3 bg-background border border-border/50 rounded-xl cursor-pointer text-left w-full hover:border-primary/50 transition-colors shadow-sm">
                  <span className="w-2 h-2 rounded-full bg-muted-foreground shrink-0"/>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-semibold text-foreground truncate">{b.name}</div>
                    <div className="text-[11px] text-muted-foreground mt-0.5">{b.county} County</div>
                  </div>
                  <IconChevron />
                </button>
              ))}
            </div>
          </div>
        ))}

        {!filtered.length && (
          <div className="text-center py-10 px-5 text-muted-foreground">
            <div className="text-[15px] font-semibold text-foreground">No beaches match</div>
            <div className="text-[13px] mt-1">Try a different search or region.</div>
          </div>
        )}
      </div>

      <TabBar />
    </div>
  );
}
