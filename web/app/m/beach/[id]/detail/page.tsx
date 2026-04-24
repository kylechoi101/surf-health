import { notFound } from "next/navigation";
import Link from "next/link";
import { getBeaches, getForecast, preferredForecastDate } from "@/lib/api";
import { riskClass, riskAdvice, mToFt, cToF, mpsToMph, fmtUv, uvLabel, fmtPeriod } from "../../../utils";
import { IconWaves, IconWind, IconSun, IconThermo, IconDrop, IconBack } from "../../../Icons";
import BeachArt from "../../../BeachArt";
import TabBar from "../../../TabBar";

export const revalidate = 0;

export default async function BeachDetail({ params }: { params: { id: string } }) {
  const [beaches, forecast] = await Promise.all([
    getBeaches(),
    getForecast(params.id, preferredForecastDate()).catch(() => null),
  ]);

  const beach = beaches.find((b) => b.id === params.id);
  if (!beach) notFound();

  const env = forecast?.environmental_summary;
  const band = forecast?.risk_band ?? "Moderate";
  const rc = riskClass(band);

  const hasLastSample = beach.latest_official_sample_at;
  const lastSampleDate = hasLastSample
    ? new Date(beach.latest_official_sample_at!).toLocaleDateString("en-US", { month: "short", day: "numeric" })
    : null;
  const daysSince = hasLastSample
    ? Math.round((Date.now() - new Date(beach.latest_official_sample_at!).getTime()) / 86400000)
    : null;

  return (
    <div className={`sh-screen ${rc}`} style={{ background: "#f2f4f7" }}>

      {/* Hero photo */}
      <div style={{ position: "relative", height: 260 }}>
        <BeachArt band={band} seed={beach.geometry.latitude} style={{ position: "absolute", inset: 0, height: "100%" }}/>
        <div style={{ position: "absolute", inset: 0,
          background: "linear-gradient(180deg, rgba(0,0,0,0.35) 0%, transparent 40%, rgba(0,0,0,0.55) 100%)"}}/>
        <div style={{ position: "absolute", top: 12, left: 16, right: 16, display: "flex", gap: 10 }}>
          <Link href={`/m/beach/${params.id}`}
            style={{ width: 38, height: 38, borderRadius: 12,
              background: "rgba(255,255,255,0.25)", backdropFilter: "blur(12px)",
              display: "flex", alignItems: "center", justifyContent: "center", color: "#fff" }}>
            <IconBack />
          </Link>
        </div>
        <div style={{ position: "absolute", left: 20, right: 20, bottom: 18, color: "#fff" }}>
          <div style={{ fontSize: 11, letterSpacing: "0.08em", textTransform: "uppercase", opacity: 0.85, fontWeight: 600 }}>
            {beach.county} County · {beach.region}
          </div>
          <h1 style={{ fontSize: 28, fontWeight: 700, marginTop: 4 }}>{beach.name}</h1>
        </div>
      </div>

      {/* Risk banner */}
      <div style={{ padding: "18px 20px 0" }}>
        <div style={{ background: "var(--risk-bg)", color: "var(--risk-deep)",
          borderRadius: 18, padding: 16, display: "flex", alignItems: "flex-start", gap: 12 }}>
          <div style={{ width: 44, height: 44, borderRadius: 14, background: "var(--risk)",
            display: "flex", alignItems: "center", justifyContent: "center", color: "#fff", flexShrink: 0 }}>
            <IconDrop size={22}/>
          </div>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: "0.06em", textTransform: "uppercase" }}>
              Water quality · today
            </div>
            <div style={{ fontSize: 22, fontWeight: 700, marginTop: 3 }}>{band}</div>
            <div style={{ fontSize: 13, marginTop: 4, opacity: 0.9, lineHeight: 1.4 }}>{riskAdvice(band)}</div>
          </div>
          {forecast && (
            <div style={{ textAlign: "right", flexShrink: 0 }}>
              <div style={{ fontSize: 28, fontWeight: 700, lineHeight: 1 }}>
                {Math.round(forecast.p_exceed * 100)}<span style={{ fontSize: 14 }}>%</span>
              </div>
              <div style={{ fontSize: 10, fontWeight: 600, opacity: 0.75 }}>exceed chance</div>
            </div>
          )}
        </div>
      </div>

      {/* Conditions grid */}
      <div style={{ padding: "24px 20px 0" }}>
        <div className="sh-section-title">Conditions</div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
          <GridStat icon={<IconWaves/>} label="Surf"
            big={mToFt(env?.wave_height_m)}
            sub={fmtPeriod(env?.dominant_period_s) || "—"}/>
          <GridStat icon={<IconThermo/>} label="Water temp"
            big={cToF(env?.water_temperature_c)}
            sub="sea surface"/>
          <GridStat icon={<IconWind/>} label="Wind"
            big={mpsToMph(env?.wind_speed_mps)}
            sub="surface"/>
          <GridStat icon={<IconSun/>} label="UV"
            big={fmtUv(env?.uv_index)}
            sub={uvLabel(env?.uv_index)}/>
        </div>
      </div>

      {/* Drivers */}
      {forecast && forecast.top_drivers.length > 0 && (
        <div style={{ padding: "24px 20px 0" }}>
          <div className="sh-section-title">What&rsquo;s driving the forecast</div>
          <div className="sh-card" style={{ padding: 0, overflow: "hidden" }}>
            {forecast.top_drivers.map((driver, i) => {
              const good = band === "Low";
              return (
                <div key={i} style={{ display: "flex", gap: 12, padding: 14,
                  borderTop: i ? "1px solid #f1f5f9" : "none" }}>
                  <div style={{ width: 26, height: 26, borderRadius: 8, flexShrink: 0,
                    background: good ? "#dcfce7" : "#fee2e2",
                    color: good ? "#15803d" : "#b91c1c",
                    display: "flex", alignItems: "center", justifyContent: "center", fontSize: 14, fontWeight: 700 }}>
                    {good ? "✓" : "!"}
                  </div>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 14, fontWeight: 600, lineHeight: 1.3 }}>{driver}</div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Last official sample */}
      {hasLastSample && (
        <div style={{ padding: "24px 20px 0" }}>
          <div className="sh-section-title">Last official sample</div>
          <div className="sh-card" style={{ display: "flex", alignItems: "center", gap: 14 }}>
            <div style={{ width: 38, height: 38, borderRadius: 10, background: "#f1f5f9",
              display: "flex", alignItems: "center", justifyContent: "center", color: "#0b4266" }}>
              <IconFlask />
            </div>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 14, fontWeight: 600 }}>
                {daysSince === 0 ? "Today" : daysSince === 1 ? "Yesterday" : `${daysSince} days ago`} · {lastSampleDate}
              </div>
              <div style={{ fontSize: 12, color: "#64748b", marginTop: 2 }}>Official county monitoring</div>
            </div>
          </div>
        </div>
      )}

      {/* Forecast footer */}
      {forecast && (
        <div style={{ padding: "20px 20px 0" }}>
          <div style={{ fontSize: 12, color: "#94a3b8", lineHeight: 1.5 }}>
            Forecast generated by <strong>{forecast.model_version}</strong> · {new Date(forecast.forecast_generated_at).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZone: "America/Los_Angeles" })} PT
          </div>
        </div>
      )}

      <TabBar beachId={params.id} />
    </div>
  );
}

function GridStat({ icon, label, big, sub }: { icon: React.ReactNode; label: string; big: string; sub: string }) {
  return (
    <div className="sh-card">
      <div style={{ display: "flex", alignItems: "center", gap: 5, color: "#64748b" }}>
        {icon}
        <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: "0.06em", textTransform: "uppercase" }}>{label}</span>
      </div>
      <div style={{ fontSize: 22, fontWeight: 700, marginTop: 6 }}>{big}</div>
      <div style={{ fontSize: 11, color: "#64748b", marginTop: 2 }}>{sub}</div>
    </div>
  );
}

function IconFlask({ size = 16 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
      <path d="M9 3h6M10 3v7l-5 9a2 2 0 0 0 1.7 3h10.6a2 2 0 0 0 1.7-3l-5-9V3" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round"/>
    </svg>
  );
}
