import { useEffect, useState } from "react";
import { View, Text, TouchableOpacity, ScrollView, StyleSheet, ActivityIndicator } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { getBeaches, getForecast, getObservations, todayLA, type BeachSummary, type ForecastRecord, type ObservationResponse } from "../../../lib/api";
import { riskAdvice, riskHead, RISK_COLORS, mToFt, cToF, mpsToMph, fmtUv, uvLabel, fmtPeriod, daysSince } from "../../../lib/utils";
import { DropRow, SeverityBar, RISK_COPY, type RiskBand } from "../../../components/RiskSystem";

export default function BeachDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [beach, setBeach] = useState<BeachSummary | null>(null);
  const [forecast, setForecast] = useState<ForecastRecord | null>(null);
  const [observations, setObservations] = useState<ObservationResponse | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!id) return;
    Promise.all([
      getBeaches().then((bs) => bs.find((b) => b.id === id) ?? null),
      getForecast(id, todayLA()).catch(() => null),
      getObservations(id).catch(() => null),
    ]).then(([b, f, o]) => { setBeach(b); setForecast(f); setObservations(o); }).finally(() => setLoading(false));
  }, [id]);

  if (loading) return (
    <View style={{ flex: 1, justifyContent: "center", alignItems: "center", backgroundColor: "#f2f4f7" }}>
      <ActivityIndicator color="#0b4266" size="large" />
    </View>
  );

  if (!beach) return null;

  const isUnsupported = beach.support_status === "unsupported";
  const band = (forecast?.risk_band ?? "Moderate") as RiskBand;
  const colors = isUnsupported ? { hero: ["#64748b", "#475569"], deep: "#334155", bg: "#e2e8f0", fill: "#94a3b8" } : (RISK_COLORS[band] ?? RISK_COLORS.Moderate);
  const env = forecast?.environmental_summary;
  const ds = daysSince(beach.latest_official_sample_at);
  const riskCopy = isUnsupported ? { head: "No model coverage yet", sub: "Showing latest official sample. Treat uncertainty seriously." } : RISK_COPY[band];

  return (
    <View style={{ flex: 1, backgroundColor: "#f2f4f7" }}>
      <ScrollView contentContainerStyle={{ paddingBottom: 48 }}>
        {/* Hero */}
        <View style={[s.heroArt, { backgroundColor: colors.hero[0] }]}>
          <SafeAreaView edges={["top"]}>
            <View style={{ flexDirection: "row", alignItems: "center", gap: 10 }}>
              <TouchableOpacity onPress={() => router.back()} style={s.backBtn}>
                <Text style={s.backText}>‹</Text>
              </TouchableOpacity>
            </View>
          </SafeAreaView>
          {/* tide-line decoration */}
          <View style={s.tideLine1} />
          <View style={s.tideLine2} />
          <View style={s.heroBottom}>
            <Text style={s.heroSub}>{beach.county} County · {beach.region}</Text>
            <Text style={s.heroTitle}>{beach.name}</Text>
          </View>
        </View>

        {/* Risk banner */}
        <View style={{ padding: 16, paddingBottom: 0 }}>
          <View style={[s.riskBanner, { backgroundColor: colors.bg }]}>
            <View style={{ flex: 1 }}>
              <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start" }}>
                <View style={{ flex: 1 }}>
                  <Text style={[s.riskEyebrow, { color: colors.deep }]}>Water quality · today</Text>
                  <Text style={[s.riskHead, { color: colors.deep }]}>{riskCopy.head}</Text>
                  <Text style={[s.riskAdvice, { color: colors.deep }]}>{riskCopy.sub}</Text>
                </View>
                <View style={{ alignItems: "flex-end", gap: 8 }}>
                  {!isUnsupported && <DropRow band={band} size={15} />}
                  {!isUnsupported && forecast && (
                    <View style={{ alignItems: "flex-end" }}>
                      <Text style={[s.pctBig, { color: colors.deep }]}>{Math.round(forecast.p_exceed * 100)}<Text style={{ fontSize: 14 }}>%</Text></Text>
                      <Text style={[s.pctSub, { color: colors.deep }]}>exceed chance</Text>
                    </View>
                  )}
                </View>
              </View>
              {!isUnsupported && (
                <View style={{ marginTop: 14 }}>
                  <Text style={[s.riskEyebrow, { color: colors.deep, marginBottom: 6 }]}>Severity</Text>
                  <SeverityBar band={band} height={7} />
                  <View style={{ flexDirection: "row", justifyContent: "space-between", marginTop: 4 }}>
                    {(["Low", "Moderate", "High", "Very High"] as RiskBand[]).map((b) => (
                      <Text key={b} style={{ fontSize: 9, color: colors.deep, opacity: 0.7, fontWeight: b === band ? "700" : "400" }}>
                        {b === "Very High" ? "V.High" : b}
                      </Text>
                    ))}
                  </View>
                </View>
              )}
            </View>
          </View>
        </View>

        {/* Active advisory */}
        {observations?.advisories?.[0]?.status === "active" && (
          <View style={{ padding: 16, paddingBottom: 0 }}>
            <View style={s.advisoryCard}>
              <Text style={s.advisoryTitle}>Official Advisory Active</Text>
              <Text style={s.advisoryBody}>An official county health advisory is currently in effect for this beach.</Text>
            </View>
          </View>
        )}

        {/* Conditions grid */}
        <View style={{ padding: 16, paddingBottom: 0 }}>
          <Text style={s.sectionLabel}>Conditions</Text>
          <View style={s.grid}>
            <GridCard icon="🌊" label="Surf" big={mToFt(env?.wave_height_m)} sub={fmtPeriod(env?.dominant_period_s) || "—"} />
            <GridCard icon="🌡" label="Water temp" big={cToF(env?.water_temperature_c)} sub="sea surface" />
            <GridCard icon="💨" label="Wind" big={mpsToMph(env?.wind_speed_mps)} sub="surface" />
            <GridCard icon="☀️" label="UV" big={fmtUv(env?.uv_index)} sub={uvLabel(env?.uv_index)} />
          </View>
        </View>

        {/* Drivers */}
        {forecast && forecast.top_drivers.length > 0 && (
          <View style={{ padding: 16, paddingBottom: 0 }}>
            <Text style={s.sectionLabel}>What&apos;s driving the forecast</Text>
            <View style={s.card}>
              {forecast.top_drivers.map((d, i) => (
                <View key={i} style={[s.driverRow, i > 0 && { borderTopWidth: 1, borderTopColor: "#f1f5f9" }]}>
                  <View style={[s.driverIcon, { backgroundColor: band === "Low" ? "#dcfce7" : "#fee2e2" }]}>
                    <Text style={{ fontSize: 12, fontWeight: "700", color: band === "Low" ? "#15803d" : "#b91c1c" }}>
                      {band === "Low" ? "✓" : "!"}
                    </Text>
                  </View>
                  <Text style={s.driverText}>{d}</Text>
                </View>
              ))}
            </View>
          </View>
        )}

        {/* Last sample */}
        {ds != null && (
          <View style={{ padding: 16, paddingBottom: 0 }}>
            <Text style={s.sectionLabel}>Last official sample</Text>
            <View style={[s.card, { flexDirection: "row", alignItems: "center", gap: 14, padding: 16 }]}>
              <View style={s.sampleIcon}>
                <Text style={{ fontSize: 18 }}>🧫</Text>
              </View>
              <View style={{ flex: 1 }}>
                <Text style={{ fontSize: 14, fontWeight: "600", color: "#0f172a" }}>
                  {ds === 0 ? "Today" : ds === 1 ? "Yesterday" : `${ds} days ago`}
                </Text>
                <Text style={{ fontSize: 12, color: "#64748b", marginTop: 2 }}>Official county monitoring</Text>
              </View>
            </View>
          </View>
        )}

        {/* Observations bar chart */}
        {observations?.observations && observations.observations.length > 0 && (
          <View style={{ padding: 16, paddingBottom: 0 }}>
            <Text style={s.sectionLabel}>Recent observations</Text>
            <View style={[s.card, { padding: 16, height: 100, flexDirection: "row", alignItems: "flex-end", gap: 3, justifyContent: "space-between" }]}>
              {[...observations.observations].reverse().map((obs, i) => {
                const maxVal = Math.max(...observations.observations.map(o => Math.log10(Math.max(o.value, 1))));
                const heightPct = Math.max((Math.log10(Math.max(obs.value, 1)) / (maxVal || 1)) * 100, 2);
                return (
                  <View key={i} style={{
                    flex: 1, height: `${heightPct}%` as any,
                    backgroundColor: obs.exceeds_stv ? "#ef4444" : "#cbd5e1",
                    borderRadius: 2, minHeight: 4,
                  }} />
                );
              })}
            </View>
            <Text style={{ fontSize: 10, color: "#94a3b8", marginTop: 6 }}>CFU/100mL — red bars exceed STV of 104</Text>
          </View>
        )}

        {/* Footer */}
        {forecast && (
          <View style={{ marginTop: 24 }}>
            <Text style={{ fontSize: 12, color: "#64748b", lineHeight: 18 }}>
              {isUnsupported ? "Model: None (latest official sample) · " : `Model: ${forecast.model_version} · `}Shorelife forecasts are not official lab results — exercise extra caution if you have a cut or compromised immune system.
            </Text>
          </View>
        )}
      </ScrollView>
    </View>
  );
}

function GridCard({ icon, label, big, sub }: { icon: string; label: string; big: string; sub: string }) {
  return (
    <View style={s.gridCard}>
      <View style={{ flexDirection: "row", alignItems: "center", gap: 4 }}>
        <Text style={{ fontSize: 13 }}>{icon}</Text>
        <Text style={s.gridLabel}>{label}</Text>
      </View>
      <Text style={s.gridBig}>{big}</Text>
      <Text style={s.gridSub}>{sub}</Text>
    </View>
  );
}

const s = StyleSheet.create({
  heroArt: { minHeight: 220, padding: 16, justifyContent: "space-between", position: "relative", overflow: "hidden" },
  backBtn: { width: 38, height: 38, borderRadius: 12, backgroundColor: "rgba(255,255,255,0.25)", alignItems: "center", justifyContent: "center" },
  backText: { color: "#fff", fontSize: 26, fontWeight: "300", lineHeight: 30 },
  tideLine1: { position: "absolute", bottom: 30, left: 0, right: 0, height: 14, backgroundColor: "rgba(255,255,255,0.08)", borderRadius: 50 },
  tideLine2: { position: "absolute", bottom: 16, left: 20, right: 20, height: 10, backgroundColor: "rgba(255,255,255,0.05)", borderRadius: 50 },
  heroBottom: { paddingBottom: 8, marginTop: 20 },
  heroSub: { color: "rgba(255,255,255,0.8)", fontSize: 11, fontWeight: "600", textTransform: "uppercase", letterSpacing: 1 },
  heroTitle: { color: "#fff", fontSize: 26, fontWeight: "700", marginTop: 4 },
  riskBanner: { borderRadius: 20, padding: 18 },
  riskEyebrow: { fontSize: 10, fontWeight: "700", textTransform: "uppercase", letterSpacing: 0.8 },
  riskHead: { fontSize: 28, fontWeight: "700", marginTop: 2 },
  riskAdvice: { fontSize: 13, marginTop: 4, lineHeight: 18 },
  pctBig: { fontSize: 28, fontWeight: "700", lineHeight: 32 },
  pctSub: { fontSize: 9, fontWeight: "600", opacity: 0.75 },
  advisoryCard: { backgroundColor: "#fee2e2", padding: 16, borderRadius: 18, borderWidth: 1, borderColor: "#fca5a5" },
  advisoryTitle: { color: "#991b1b", fontWeight: "700", fontSize: 13, textTransform: "uppercase", letterSpacing: 0.5 },
  advisoryBody: { color: "#991b1b", marginTop: 4, fontSize: 14, lineHeight: 20 },
  sectionLabel: { fontSize: 10, fontWeight: "700", color: "#64748b", textTransform: "uppercase", letterSpacing: 1, marginBottom: 10 },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  gridCard: { width: "48%", backgroundColor: "#fff", borderRadius: 16, borderWidth: 1, borderColor: "#e5e7eb", padding: 14 },
  gridLabel: { fontSize: 9, fontWeight: "700", color: "#64748b", textTransform: "uppercase", letterSpacing: 0.5 },
  gridBig: { fontSize: 20, fontWeight: "700", color: "#0f172a", marginTop: 6 },
  gridSub: { fontSize: 10, color: "#64748b", marginTop: 2 },
  card: { backgroundColor: "#fff", borderRadius: 18, borderWidth: 1, borderColor: "#e5e7eb", overflow: "hidden" },
  driverRow: { flexDirection: "row", alignItems: "flex-start", gap: 12, padding: 14 },
  driverIcon: { width: 26, height: 26, borderRadius: 8, alignItems: "center", justifyContent: "center", flexShrink: 0 },
  driverText: { flex: 1, fontSize: 14, fontWeight: "500", color: "#0f172a", lineHeight: 20 },
  sampleIcon: { width: 38, height: 38, borderRadius: 10, backgroundColor: "#f1f5f9", alignItems: "center", justifyContent: "center" },
});
