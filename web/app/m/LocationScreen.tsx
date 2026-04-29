"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import type { BeachSummary } from "@/lib/api";
import { IconSearch, IconLocate, IconChevron, IconClose } from "./Icons";
import { LockupHorizontal } from "@/components/Lockup";

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
    <div className="h-[100dvh] flex flex-col relative overflow-hidden bg-gradient-to-b from-sky-900 via-sky-700 to-sky-400 text-white">
      {/* Ambient bg */}
      <svg viewBox="0 0 400 700" preserveAspectRatio="none"
        className="absolute inset-0 w-full h-full opacity-40 pointer-events-none">
        <path d="M0 420 C 80 400, 160 460, 240 430 S 400 410, 400 430 L400 700 L0 700 Z" fill="#f4e5b9"/>
        <path d="M0 400 C 80 380, 160 440, 240 410 S 400 390, 400 410" stroke="#fff" strokeWidth="1" opacity="0.5" fill="none"/>
        <circle cx="320" cy="120" r="50" fill="#ffd97a" opacity="0.85"/>
      </svg>

      <div className="relative px-5 pt-4 z-10">
        <div className="flex items-center gap-2.5 mt-6">
          <div className="bg-white/20 rounded-xl p-1.5 backdrop-blur-sm">
            <LockupHorizontal size={20} ink="#fff" />
          </div>
        </div>
        <h1 className="text-4xl font-bold leading-tight mt-9 max-w-[300px]">
          Find out if the water&rsquo;s clean
          <span className="opacity-70 font-light block mt-1">—before you paddle out.</span>
        </h1>
        <p className="text-[15px] opacity-80 mt-4 leading-relaxed max-w-[300px]">
          Daily bacteria + surf forecast for 290+ California beaches.
        </p>
      </div>

      {/* Bottom sheet */}
      <div className="mt-auto bg-background text-foreground rounded-t-[28px] px-5 pt-5 pb-8 z-20 shadow-[0_-20px_60px_rgba(0,0,0,0.2)]">
        {/* Search */}
        <div className="flex items-center gap-2.5 bg-muted/50 rounded-2xl p-3 border border-border/50 focus-within:border-primary transition-colors">
          <IconSearch />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search beaches, cities, counties"
            className="flex-1 bg-transparent border-none outline-none text-[15px] text-foreground placeholder:text-muted-foreground"
          />
          {q && (
            <button onClick={() => setQ("")} className="text-muted-foreground p-1 hover:text-foreground">
              <IconClose />
            </button>
          )}
        </div>

        {q ? (
          <div className="mt-3.5 max-h-[240px] overflow-y-auto">
            {results.map((b) => (
              <button key={b.id} onClick={() => pick(b)}
                className="w-full flex items-center gap-3 py-2.5 px-1 border-b border-border/50 bg-transparent text-left hover:bg-muted/30 transition-colors">
                <span className="w-2 h-2 rounded-full bg-muted-foreground shrink-0"/>
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-semibold text-foreground truncate">{b.name}</div>
                  <div className="text-[11px] text-muted-foreground mt-0.5">{b.county} County · {b.region}</div>
                </div>
                <IconChevron />
              </button>
            ))}
            {!results.length && (
              <p className="text-[13px] text-muted-foreground py-3 px-1">
                No matches — try another search.
              </p>
            )}
          </div>
        ) : (
          <div className="mt-4">
            <div className="text-[11px] font-bold text-muted-foreground uppercase tracking-widest mb-2 px-1">
              Nearby beaches
            </div>
            {beaches.slice(0, 4).map((b) => (
              <button key={b.id} onClick={() => pick(b)}
                className="w-full flex items-center gap-3 py-2.5 px-1 border-b border-border/50 bg-transparent text-left hover:bg-muted/30 transition-colors">
                <span className="w-2 h-2 rounded-full bg-muted-foreground shrink-0"/>
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-semibold text-foreground truncate">{b.name}</div>
                  <div className="text-[11px] text-muted-foreground mt-0.5">{b.county} County</div>
                </div>
                <IconChevron />
              </button>
            ))}
            <button
              onClick={() => router.push("/m/search")}
              className="w-full mt-3.5 p-3 rounded-xl border border-border/50 bg-muted/30 text-primary font-semibold text-sm transition-colors hover:bg-muted/50">
              Browse all beaches →
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
