import { useEffect, useState } from "react";
import { View, Text, TouchableOpacity, ScrollView, StyleSheet, ActivityIndicator } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { getBeaches, getForecast, getObservations, todayLA, type BeachSummary, type ForecastRecord, type ObservationResponse } from "../../../lib/api";
import { riskAdvice, RISK_COLORS, mToFt, cToF, mpsToMph, fmtUv, uvLabel, fmtPeriod, daysSince } from "../../../lib/utils";

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

  const band = forecast?.risk_band ?? "Moderate";
  const colors = RISK_COLORS[band] ?? RISK_COLORS.Moderate;
  const env = forecast?.environmental_summary;
  const ds = daysSince(beach.latest_official_sample_at);

  return (
    <View style={{ flex: 1, backgroundColor: "#f2f4f7" }}>
      <ScrollView contentContainerStyle={{ paddingBottom: 40 }}>
        {/* Hero art */}
        <View style={[s.heroArt, { backgroundColor: colors.hero[0] }]}>
          <SafeAreaView edges={["top"]}>
            <TouchableOpacity onPress={() => router.back()} style={s.backBtn}>
              <Text style={s.backText}>‹</Text>
            </TouchableOpacity>
          </SafeAreaView>
          <View style={s.heroBottom}>
            <Text style={s.heroSub}>{beach.county} County · {beach.region}</Text>
            <Text style={s.heroTitle}>{beach.name}</Text>
          </View>
        </View>

        {/* Risk banner */}
        <View style={{ padding: 16, paddingBottom: 0 }}>
          <View style={[s.riskBanner, { backgroundColor: colors.bg }]}>
            <View style={[s.riskIcon, { backgroundColor: colors.hero[0] }]}>
              <Text style={{ fontSize: 20 }}>💧</Text>
            </View>
            <View style={{ flex: 1 }}>
              <Text style={[s.riskBannerLabel, { color: colors.deep }]}>
                Water quality · today {forecast && forecast.forecast_age_hours !== undefined && forecast.forecast_age_hours > 24 && `(${Math.floor(forecast.forecast_age_hours / 24)}d old)`}
              </Text>
              <Text style={[s.riskBannerBand, { color: colors.deep }]}>{band}</Text>
              <Text style={[s.riskBannerAdvice, { color: colors.deep }]}>{riskAdvice(band)}</Text>
            </View>
            {forecast && (
              <View style={{ alignItems: "flex-end" }}>
                <Text style={[s.pctBig, { color: colors.deep }]}>{Math.round(forecast.p_exceed * 100)}<Text style={{ fontSize: 14 }}>%</Text></Text>
                <Text style={[s.pctSub, { color: colors.deep }]}>exceed chance</Text>
              </View>
            )}
          </View>
        </View>

        {observations && observations.advisories && observations.advisories.length > 0 && observations.advisories[0].status === "active" && (
          <View style={{ padding: 16, paddingBottom: 0 }}>
            <View style={{ backgroundColor: "#fee2e2", padding: 16, borderRadius: 18, borderWidth: 1, borderColor: "#fca5a5" }}>
              <Text style={{ color: "#991b1b", fontWeight: "700", fontSize: 13, textTransform: "uppercase", letterSpacing: 0.5 }}>Official Advisory</Text>
              <Text style={{ color: "#991b1b", marginTop: 4, fontSize: 15, lineHeight: 22 }}>
                An official county health advisory is currently active for this beach.
              </Text>
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

        {/* Last official sample */}
        {ds != null && (
          <View style={{ padding: 16, paddingBottom: 0 }}>
            <Text style={s.sectionLabel}>Last official sample</Text>
            <View style={[s.card, { flexDirection: "row", alignItems: "center", gap: 14 }]}>
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

        {/* Observations chart */}
        {observations && observations.observations && observations.observations.length > 0 && (
          <View style={{ padding: 16, paddingBottom: 0 }}>
            <Text style={s.sectionLabel}>Recent Observations</Text>
            <View style={[s.card, { padding: 16, height: 100, flexDirection: "row", alignItems: "flex-end", gap: 3, justifyContent: "space-between" }]}>
              {[...observations.observations].reverse().map((obs, i) => {
                const maxVal = Math.max(...observations.observations.map(o => Math.log10(Math.max(o.value, 1))));
                const valLog = Math.log10(Math.max(obs.value, 1));
                const heightPct = Math.max((valLog / (maxVal || 1)) * 100, 2);
                return (
                  <View key={i} style={{ flex: 1, backgroundColor: obs.exceeds_stv ? "#ef4444" : "#cbd5e1", height: `${heightPct}%`, borderRadius: 2, minHeight: 4 }} />
                );
              })}
            </View>
          </View>
        )}

        {/* Footer */}
        {forecast && (
          <View style={{ padding: 16 }}>
            <Text style={{ fontSize: 12, color: "#94a3b8", lineHeight: 18 }}>
              Model: {forecast.model_version} · This is a forecast, not a direct lab result — treat uncertainty seriously if you have a cut or a weaker immune system.
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
  heroArt: { height: 240, padding: 16, justifyContent: "space-between" },
  backBtn: { width: 38, height: 38, borderRadius: 12, backgroundColor: "rgba(255,255,255,0.25)", alignItems: "center", justifyContent: "center" },
  backText: { color: "#fff", fontSize: 26, fontWeight: "300", lineHeight: 30 },
  heroBottom: { paddingBottom: 8 },
  heroSub: { color: "rgba(255,255,255,0.8)", fontSize: 11, fontWeight: "600", textTransform: "uppercase", letterSpacing: 1 },
  heroTitle: { color: "#fff", fontSize: 26, fontWeight: "700", marginTop: 4 },
  riskBanner: { borderRadius: 18, padding: 16, flexDirection: "row", alignItems: "flex-start", gap: 12 },
  riskIcon: { width: 44, height: 44, borderRadius: 14, alignItems: "center", justifyContent: "center" },
  riskBannerLabel: { fontSize: 10, fontWeight: "700", textTransform: "uppercase", letterSpacing: 0.5 },
  riskBannerBand: { fontSize: 20, fontWeight: "700", marginTop: 2 },
  riskBannerAdvice: { fontSize: 12, marginTop: 3, lineHeight: 17 },
  pctBig: { fontSize: 26, fontWeight: "700", lineHeight: 30 },
  pctSub: { fontSize: 9, fontWeight: "600", opacity: 0.75 },
  sectionLabel: { fontSize: 11, fontWeight: "700", color: "#64748b", textTransform: "uppercase", letterSpacing: 1, marginBottom: 10 },
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
