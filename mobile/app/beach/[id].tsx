import { useEffect, useState } from "react";
import { View, Text, TouchableOpacity, ScrollView, StyleSheet, ActivityIndicator, Share } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { getBeaches, getForecast, todayLA, type BeachSummary, type ForecastRecord } from "../../lib/api";
import { findModeledBeach } from "../../lib/coverage";
import { riskAdvice, riskHead, RISK_COLORS, mToFt, cToF, mpsToMph, fmtPeriod, fmtUv } from "../../lib/utils";
import { palette } from "../../lib/theme";
import { DropRow, SeverityBar, type RiskBand } from "../../components/RiskSystem";

export default function BeachHome() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [beach, setBeach] = useState<BeachSummary | null>(null);
  const [forecast, setForecast] = useState<ForecastRecord | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!id) return;
    Promise.all([
      getBeaches().then((bs) => findModeledBeach(bs, id)),
      getForecast(id, todayLA()).catch(() => null),
    ]).then(([b, f]) => {
      setBeach(b);
      setForecast(f);
    }).finally(() => setLoading(false));
  }, [id]);

  if (loading) {
    return (
      <View style={{ flex: 1, justifyContent: "center", alignItems: "center", backgroundColor: palette.navy }}>
        <ActivityIndicator color={palette.bone} size="large" />
      </View>
    );
  }

  if (!beach) {
    return (
      <SafeAreaView style={{ flex: 1, justifyContent: "center", alignItems: "center", backgroundColor: palette.bone }}>
        <Text style={{ fontSize: 16, color: palette.muted }}>Beach not found</Text>
        <TouchableOpacity onPress={() => router.back()} style={{ marginTop: 16, flexDirection: "row", alignItems: "center", gap: 6 }}>
          <Feather name="arrow-left" size={14} color={palette.navy} />
          <Text style={{ color: palette.navy, fontWeight: "600" }}>Go back</Text>
        </TouchableOpacity>
      </SafeAreaView>
    );
  }

  const band = ((forecast?.official_advisory_active ? "Very High" : forecast?.risk_band) ?? "Moderate") as RiskBand;
  const colors = RISK_COLORS[band] ?? RISK_COLORS.Moderate;
  const env = forecast?.environmental_summary;

  async function onShare() {
    await Share.share({
      message: `${beach!.name} water quality: ${riskHead(band)} ${riskAdvice(band)} — kylechoi101.github.io/surf-health/b/?id=${id}`,
      url: `https://kylechoi101.github.io/surf-health/b/?id=${id}`,
    });
  }

  return (
    <View style={{ flex: 1 }}>
      <ScrollView style={{ flex: 1 }} contentContainerStyle={{ paddingBottom: 100 }}>
        {/* Hero */}
        <View style={[s.hero, { backgroundColor: colors.hero[0] }]}>
          <SafeAreaView edges={["top"]}>
            {/* Nav row */}
            <View style={s.navRow}>
              <TouchableOpacity onPress={() => router.back()} style={s.iconBtn}>
                <Feather name="chevron-left" size={20} color={palette.white} />
              </TouchableOpacity>
              <TouchableOpacity onPress={() => router.push("/search" as any)} style={s.locationBtn}>
                <Text style={s.locationText} numberOfLines={1}>{beach.name}</Text>
                <Feather name="chevron-right" size={14} color="rgba(255,255,255,0.7)" />
              </TouchableOpacity>
              <TouchableOpacity onPress={onShare} style={s.iconBtn}>
                <Feather name="share" size={15} color={palette.white} />
              </TouchableOpacity>
            </View>

            {/* Big answer */}
            <View style={s.answerBlock}>
              <Text style={s.answerLabel}>Today&apos;s modeled risk</Text>
              {forecast?.official_advisory_active && (
                <View style={s.advisoryPill}>
                  <Text style={s.advisoryPillText}>OFFICIAL ADVISORY ACTIVE</Text>
                </View>
              )}
              {forecast && forecast.forecast_age_hours !== undefined && forecast.forecast_age_hours > 24 && (
                <View style={s.staleBadge}>
                  <Text style={{ fontSize: 11, fontWeight: "600", color: "rgba(255,255,255,0.85)" }}>
                    Forecast is {Math.floor(forecast.forecast_age_hours / 24)}d old
                  </Text>
                </View>
              )}
              <Text style={s.verdict}>{riskHead(band)}</Text>
              <Text style={s.advice}>{riskAdvice(band)}</Text>
              <View style={s.dropSeverityRow}>
                <DropRow band={band} size={16} />
                <View style={{ flex: 1, marginLeft: 12 }}>
                  <SeverityBar band={band} height={5} />
                </View>
              </View>
            </View>

            {/* Stat tiles */}
            <View style={s.stats}>
              <StatTile iconName="droplet" label="Bacteria" value={forecast ? `${Math.round(forecast.p_exceed * 100)}%` : "—"} sub="exceed chance" />
              <StatTile iconName="trending-up" label="Surf" value={mToFt(env?.wave_height_m)} sub={fmtPeriod(env?.dominant_period_s) || "—"} />
              <StatTile iconName="thermometer" label="Water" value={cToF(env?.water_temperature_c)} sub={env?.uv_index != null ? `UV ${fmtUv(env.uv_index)}` : "—"} />
              <StatTile iconName="wind" label="Wind" value={mpsToMph(env?.wind_speed_mps)} sub="surface" />
            </View>

            {/* Detail CTA */}
            <TouchableOpacity
              onPress={() => router.push(`/beach/${id}/detail` as any)}
              style={s.detailCta}
              activeOpacity={0.8}>
              <Text style={s.detailCtaText}>See what&apos;s driving this forecast</Text>
              <Feather name="arrow-right" size={14} color={palette.white} style={{ marginLeft: 6 }} />
            </TouchableOpacity>
          </SafeAreaView>
        </View>

        {/* Drivers preview */}
        {forecast && forecast.top_drivers.length > 0 && (
          <View style={s.section}>
            <Text style={s.sectionLabel}>Key factors</Text>
            {forecast.top_drivers.slice(0, 3).map((d, i) => {
              const positive = band === "Low";
              return (
                <View key={i} style={[s.driverRow, i > 0 && { borderTopWidth: 1, borderTopColor: palette.lineSoft }]}>
                  <View style={[s.driverIcon, { backgroundColor: positive ? "#dcfce7" : "#fee2e2" }]}>
                    <Feather
                      name={positive ? "check" : "alert-circle"}
                      size={13}
                      color={positive ? "#15803d" : "#b91c1c"}
                    />
                  </View>
                  <Text style={s.driverText}>{d}</Text>
                </View>
              );
            })}
          </View>
        )}

        {/* Forecast note */}
        {forecast && (
          <View style={{ padding: 20, paddingTop: 12 }}>
            <Text style={{ fontSize: 11, color: palette.muted, lineHeight: 17 }}>
              Model: {forecast.model_version} · This is a beta model estimate, not a lab result. Treat uncertainty seriously if you have a cut or weaker immune system.
            </Text>
          </View>
        )}
      </ScrollView>
    </View>
  );
}

function StatTile({ iconName, label, value, sub }: { iconName: keyof typeof Feather.glyphMap; label: string; value: string; sub: string }) {
  return (
    <View style={s.tile}>
      <View style={{ flexDirection: "row", alignItems: "center", gap: 5 }}>
        <Feather name={iconName} size={11} color="rgba(255,255,255,0.85)" />
        <Text style={s.tileLabel}>{label}</Text>
      </View>
      <Text style={s.tileValue}>{value}</Text>
      <Text style={s.tileSub}>{sub}</Text>
    </View>
  );
}

const s = StyleSheet.create({
  hero: { padding: 20, paddingBottom: 28 },
  navRow: { flexDirection: "row", alignItems: "center", gap: 10, marginTop: 4 },
  iconBtn: {
    width: 36, height: 36, borderRadius: 12,
    backgroundColor: "rgba(255,255,255,0.2)",
    alignItems: "center", justifyContent: "center",
  },
  locationBtn: {
    flex: 1, flexDirection: "row", alignItems: "center", gap: 6,
    paddingHorizontal: 12, paddingVertical: 9,
    borderRadius: 12, backgroundColor: "rgba(255,255,255,0.10)",
  },
  locationText: { flex: 1, color: "rgba(255,255,255,0.92)", fontSize: 14, fontWeight: "600" },
  staleBadge: { backgroundColor: "rgba(0,0,0,0.15)", paddingHorizontal: 8, paddingVertical: 3, borderRadius: 6, alignSelf: "flex-start", marginBottom: 6 },
  advisoryPill: { backgroundColor: "rgba(0,0,0,0.22)", paddingHorizontal: 10, paddingVertical: 4, borderRadius: 999, alignSelf: "flex-start", marginBottom: 8 },
  advisoryPillText: { fontSize: 10, fontWeight: "800", color: "rgba(255,255,255,0.92)", letterSpacing: 0.7 },
  answerBlock: { marginTop: 22 },
  answerLabel: { color: "rgba(255,255,255,0.8)", fontSize: 11, fontWeight: "700", letterSpacing: 1.2, textTransform: "uppercase" },
  verdict: { color: palette.white, fontSize: 52, fontWeight: "700", lineHeight: 56, letterSpacing: -0.5, marginTop: 4 },
  advice: { color: "rgba(255,255,255,0.9)", fontSize: 14, lineHeight: 20, marginTop: 6, maxWidth: 300 },
  dropSeverityRow: { flexDirection: "row", alignItems: "center", marginTop: 14 },
  stats: { flexDirection: "row", gap: 8, marginTop: 18 },
  tile: { flex: 1, padding: 12, backgroundColor: "rgba(255,255,255,0.18)", borderRadius: 14 },
  tileLabel: { fontSize: 9, fontWeight: "700", color: "rgba(255,255,255,0.85)", textTransform: "uppercase", letterSpacing: 0.6 },
  tileValue: { fontSize: 22, fontWeight: "700", color: palette.white, marginTop: 4, letterSpacing: -0.3 },
  tileSub: { fontSize: 10, color: "rgba(255,255,255,0.72)", marginTop: 2 },
  detailCta: {
    marginTop: 16, paddingVertical: 13, paddingHorizontal: 16,
    backgroundColor: "rgba(255,255,255,0.20)",
    borderRadius: 14,
    flexDirection: "row", alignItems: "center", justifyContent: "center",
  },
  detailCtaText: { color: palette.white, fontSize: 14, fontWeight: "600" },
  section: { backgroundColor: palette.bone, marginHorizontal: 16, marginTop: 16, borderRadius: 18, borderWidth: 1, borderColor: palette.lineSoft, overflow: "hidden" },
  sectionLabel: { fontSize: 10, fontWeight: "700", color: palette.muted, textTransform: "uppercase", letterSpacing: 1.2, padding: 14, paddingBottom: 6 },
  driverRow: { flexDirection: "row", alignItems: "flex-start", gap: 12, padding: 14 },
  driverIcon: { width: 26, height: 26, borderRadius: 8, alignItems: "center", justifyContent: "center" },
  driverText: { flex: 1, fontSize: 14, fontWeight: "500", color: palette.ink, lineHeight: 20 },
});
