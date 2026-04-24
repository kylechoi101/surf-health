import { notFound } from "next/navigation";
import Link from "next/link";
import { getBeaches, getForecast, preferredForecastDate } from "@/lib/api";
import type { BeachSummary, ForecastRecord } from "@/lib/api";
import { riskClass, riskVerdict, riskAdvice, mToFt, cToF, mpsToMph, fmtUv, fmtPeriod } from "../../utils";
import { IconWaves, IconThermo, IconFlask, IconSearch } from "../../Icons";
import TabBar from "../../TabBar";
import BeachArt from "../../BeachArt";

export const revalidate = 0;

export default async function BeachHome({ params }: { params: { id: string } }) {
  const [beaches, forecast] = await Promise.all([
    getBeaches(),
    getForecast(params.id, preferredForecastDate()).catch(() => null),
  ]);

  const beach = beaches.find((b) => b.id === params.id);
  if (!beach) notFound();

  const env = forecast?.environmental_summary;
  const nearby = beaches
    .filter((b) => b.county === beach.county && b.id !== beach.id)
    .slice(0, 5);

  const band = forecast?.risk_band ?? "Moderate";
  const rc = riskClass(band);

  return (
    <div className={`sh-screen ${rc}`}>
      {/* HERO */}
      <div className="hero-wash" style={{ color: "#fff", padding: "8px 20px 24px", position: "relative", overflow: "hidden" }}>
        {/* subtle texture */}
        <svg viewBox="0 0 400 280" preserveAspectRatio="none"
          style={{ position: "absolute", inset: 0, width: "100%", height: "100%", opacity: 0.2, pointerEvents: "none" }}>
          <circle cx="340" cy="50" r="46" fill="#fff"/>
          <path d="M0 220 C 80 210, 160 240, 240 220 S 400 210, 400 220 L400 280 L0 280 Z" fill="#fff" opacity="0.12"/>
        </svg>
        <div style={{ position: "relative" }}>
          {/* location row */}
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 16 }}>
            <Link href="/m/search"
              style={{ display: "flex", alignItems: "center", gap: 4, background: "none", border: "none",
                color: "#fff", fontSize: 14, fontWeight: 600, padding: 0, cursor: "pointer" }}>
              {beach.name}
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
                <path d="m9 6 6 6-6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
            </Link>
            <span style={{ marginLeft: "auto", fontSize: 11, opacity: 0.75 }}>
              Updated {new Date().toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", timeZone: "America/Los_Angeles" })}
            </span>
          </div>

          {/* Big answer */}
          <div style={{ marginTop: 28 }}>
            <div style={{ fontSize: 13, fontWeight: 600, letterSpacing: "0.08em", textTransform: "uppercase", opacity: 0.85 }}>
              Can I swim today?
            </div>
            <h1 style={{ fontSize: 58, lineHeight: 0.95, fontWeight: 700, marginTop: 6 }}>
              {riskVerdict(band)}
            </h1>
            <p style={{ fontSize: 15, marginTop: 10, lineHeight: 1.45, maxWidth: 300, opacity: 0.95 }}>
              {riskAdvice(band)}
            </p>
          </div>

          {/* Stat tiles */}
          <div style={{ display: "flex", gap: 10, marginTop: 22 }}>
            <StatTile icon={<IconFlask />} label="Bacteria" value={forecast ? `${Math.round(forecast.p_exceed * 100)}%` : "—"} sub="exceed chance"/>
            <StatTile icon={<IconWaves />} label="Surf" value={mToFt(env?.wave_height_m)} sub={fmtPeriod(env?.dominant_period_s) || "—"}/>
            <StatTile icon={<IconThermo />} label="Water" value={cToF(env?.water_temperature_c)} sub={env?.uv_index != null ? `UV ${fmtUv(env.uv_index)}` : "—"}/>
          </div>

          <Link href={`/m/beach/${params.id}/detail`}
            style={{ display: "block", width: "100%", marginTop: 20, padding: 14,
              border: "none", borderRadius: 14, background: "rgba(255,255,255,0.22)",
              backdropFilter: "blur(8px)", color: "#fff",
              fontSize: 14, fontWeight: 600, cursor: "pointer", textAlign: "center" }}>
            See what&rsquo;s driving this forecast →
          </Link>
        </div>
      </div>

      {/* Nearby */}
      {nearby.length > 0 && (
        <div style={{ padding: "24px 0 0" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", padding: "0 20px", marginBottom: 10 }}>
            <div className="sh-section-title" style={{ marginBottom: 0 }}>Nearby beaches</div>
            <Link href="/m/search" style={{ color: "#0b4266", fontSize: 13, fontWeight: 600 }}>All →</Link>
          </div>
          <div style={{ padding: "0 20px", display: "flex", flexDirection: "column", gap: 8 }}>
            {nearby.map((b, i) => (
              <Link key={b.id} href={`/m/beach/${b.id}`}
                style={{ display: "flex", alignItems: "center", gap: 12, padding: "12px 14px",
                  background: "#fff", border: "1px solid #e5e7eb", borderRadius: 14, textDecoration: "none" }}>
                <div style={{ width: 44, height: 44, borderRadius: 11, overflow: "hidden", flexShrink: 0 }}>
                  <BeachArt band="Moderate" seed={i} />
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 14, fontWeight: 600, color: "#0f172a" }}>{b.name}</div>
                  <div style={{ fontSize: 11, color: "#64748b", marginTop: 2 }}>{b.county} County</div>
                </div>
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" style={{ color: "#cbd5e1", flexShrink: 0 }}>
                  <path d="m9 6 6 6-6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                </svg>
              </Link>
            ))}
          </div>
        </div>
      )}

      <TabBar beachId={params.id} />
    </div>
  );
}

function StatTile({ icon, label, value, sub }: { icon: React.ReactNode; label: string; value: string; sub: string }) {
  return (
    <div style={{ flex: 1, padding: "10px 12px", background: "rgba(255,255,255,0.18)",
      borderRadius: 14, backdropFilter: "blur(8px)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 5, opacity: 0.85 }}>
        {icon}
        <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: "0.05em", textTransform: "uppercase" }}>{label}</span>
      </div>
      <div style={{ fontSize: 22, fontWeight: 700, marginTop: 4 }}>{value}</div>
      <div style={{ fontSize: 10, opacity: 0.8, marginTop: 2 }}>{sub}</div>
    </div>
  );
}
