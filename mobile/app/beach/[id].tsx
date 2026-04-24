import { useEffect, useState } from "react";
import { View, Text, TouchableOpacity, ScrollView, StyleSheet, ActivityIndicator } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { getBeaches, getForecast, todayLA, type BeachSummary, type ForecastRecord } from "../../lib/api";
import { riskVerdict, riskAdvice, RISK_COLORS, mToFt, cToF, fmtPeriod, fmtUv } from "../../lib/utils";

export default function BeachHome() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [beach, setBeach] = useState<BeachSummary | null>(null);
  const [forecast, setForecast] = useState<ForecastRecord | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!id) return;
    Promise.all([
      getBeaches().then((bs) => bs.find((b) => b.id === id) ?? null),
      getForecast(id, todayLA()).catch(() => null),
    ]).then(([b, f]) => {
      setBeach(b);
      setForecast(f);
    }).finally(() => setLoading(false));
  }, [id]);

  if (loading) {
    return (
      <View style={{ flex: 1, justifyContent: "center", alignItems: "center", backgroundColor: "#0b4266" }}>
        <ActivityIndicator color="#fff" size="large" />
      </View>
    );
  }

  if (!beach) {
    return (
      <SafeAreaView style={{ flex: 1, justifyContent: "center", alignItems: "center" }}>
        <Text style={{ fontSize: 16, color: "#64748b" }}>Beach not found</Text>
        <TouchableOpacity onPress={() => router.back()} style={{ marginTop: 16 }}>
          <Text style={{ color: "#0b4266", fontWeight: "600" }}>← Go back</Text>
        </TouchableOpacity>
      </SafeAreaView>
    );
  }

  const band = forecast?.risk_band ?? "Moderate";
  const colors = RISK_COLORS[band] ?? RISK_COLORS.Moderate;
  const env = forecast?.environmental_summary;

  return (
    <View style={{ flex: 1 }}>
      <ScrollView style={{ flex: 1 }} contentContainerStyle={{ paddingBottom: 100 }}>
        {/* Hero */}
        <View style={[s.hero, { backgroundColor: colors.hero[0] }]}>
          <SafeAreaView edges={["top"]}>
            {/* Nav row */}
            <View style={s.navRow}>
              <TouchableOpacity onPress={() => router.back()} style={s.backBtn}>
                <Text style={s.backText}>‹</Text>
              </TouchableOpacity>
              <TouchableOpacity onPress={() => router.push("/search" as any)} style={s.locationBtn}>
                <Text style={s.locationText}>{beach.name}  ›</Text>
              </TouchableOpacity>
            </View>

            {/* Big answer */}
            <View style={s.answerBlock}>
              <Text style={s.answerLabel}>Can I swim today?</Text>
              <Text style={s.verdict}>{riskVerdict(band)}</Text>
              <Text style={s.advice}>{riskAdvice(band)}</Text>
            </View>

            {/* Stat tiles */}
            <View style={s.stats}>
              <StatTile icon="🧫" label="Bacteria" value={forecast ? `${Math.round(forecast.p_exceed * 100)}%` : "—"} sub="exceed chance" />
              <StatTile icon="🌊" label="Surf" value={mToFt(env?.wave_height_m)} sub={fmtPeriod(env?.dominant_period_s) || "—"} />
              <StatTile icon="🌡" label="Water" value={cToF(env?.water_temperature_c)} sub={env?.uv_index != null ? `UV ${fmtUv(env.uv_index)}` : "—"} />
            </View>

            {/* Detail CTA */}
            <TouchableOpacity
              onPress={() => router.push(`/beach/${id}/detail` as any)}
              style={s.detailCta}>
              <Text style={s.detailCtaText}>See what&apos;s driving this forecast  →</Text>
            </TouchableOpacity>
          </SafeAreaView>
        </View>

        {/* Drivers preview */}
        {forecast && forecast.top_drivers.length > 0 && (
          <View style={s.section}>
            <Text style={s.sectionLabel}>Key factors</Text>
            {forecast.top_drivers.slice(0, 2).map((d, i) => (
              <View key={i} style={s.driverRow}>
                <View style={[s.driverIcon, { backgroundColor: band === "Low" ? "#dcfce7" : "#fee2e2" }]}>
                  <Text style={{ fontSize: 13, fontWeight: "700", color: band === "Low" ? "#15803d" : "#b91c1c" }}>
                    {band === "Low" ? "✓" : "!"}
                  </Text>
                </View>
                <Text style={s.driverText}>{d}</Text>
              </View>
            ))}
          </View>
        )}

        {/* Forecast note */}
        {forecast && (
          <View style={{ padding: 20, paddingTop: 0 }}>
            <Text style={{ fontSize: 12, color: "#94a3b8", lineHeight: 18 }}>
              Forecast: {forecast.model_version} · This is a model output, not a lab result.
            </Text>
          </View>
        )}
      </ScrollView>
    </View>
  );
}

function StatTile({ icon, label, value, sub }: { icon: string; label: string; value: string; sub: string }) {
  return (
    <View style={s.tile}>
      <View style={{ flexDirection: "row", alignItems: "center", gap: 4 }}>
        <Text style={{ fontSize: 12 }}>{icon}</Text>
        <Text style={s.tileLabel}>{label}</Text>
      </View>
      <Text style={s.tileValue}>{value}</Text>
      <Text style={s.tileSub}>{sub}</Text>
    </View>
  );
}

const s = StyleSheet.create({
  hero: { padding: 20, paddingBottom: 28 },
  navRow: { flexDirection: "row", alignItems: "center", gap: 8, marginTop: 4 },
  backBtn: { padding: 4 },
  backText: { color: "#fff", fontSize: 28, lineHeight: 32, fontWeight: "300" },
  locationBtn: { flex: 1 },
  locationText: { color: "#fff", fontSize: 14, fontWeight: "600" },
  answerBlock: { marginTop: 24 },
  answerLabel: { color: "rgba(255,255,255,0.85)", fontSize: 13, fontWeight: "600", letterSpacing: 1, textTransform: "uppercase" },
  verdict: { color: "#fff", fontSize: 56, fontWeight: "700", lineHeight: 60, marginTop: 4 },
  advice: { color: "rgba(255,255,255,0.9)", fontSize: 15, lineHeight: 22, marginTop: 8, maxWidth: 300 },
  stats: { flexDirection: "row", gap: 8, marginTop: 20 },
  tile: { flex: 1, padding: 10, backgroundColor: "rgba(255,255,255,0.18)", borderRadius: 14 },
  tileLabel: { fontSize: 9, fontWeight: "700", color: "rgba(255,255,255,0.85)", textTransform: "uppercase", letterSpacing: 0.5 },
  tileValue: { fontSize: 20, fontWeight: "700", color: "#fff", marginTop: 4 },
  tileSub: { fontSize: 9, color: "rgba(255,255,255,0.75)", marginTop: 2 },
  detailCta: {
    marginTop: 18, padding: 14, backgroundColor: "rgba(255,255,255,0.22)",
    borderRadius: 14, alignItems: "center",
  },
  detailCtaText: { color: "#fff", fontSize: 14, fontWeight: "600" },
  section: { padding: 20, paddingBottom: 0 },
  sectionLabel: { fontSize: 11, fontWeight: "700", color: "#64748b", textTransform: "uppercase", letterSpacing: 1, marginBottom: 10 },
  driverRow: { flexDirection: "row", alignItems: "flex-start", gap: 12, marginBottom: 8 },
  driverIcon: { width: 26, height: 26, borderRadius: 8, alignItems: "center", justifyContent: "center" },
  driverText: { flex: 1, fontSize: 14, fontWeight: "500", color: "#0f172a", lineHeight: 20 },
});
