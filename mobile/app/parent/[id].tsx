import { useEffect, useState } from "react";
import { ActivityIndicator, ScrollView, StyleSheet, Text, TouchableOpacity, View } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import {
  getBeaches,
  getForecast,
  getParentBeaches,
  todayLA,
  type BeachSummary,
  type ForecastRecord,
  type ParentBeachSummary,
} from "../../lib/api";
import { filterModeledBeaches, findModeledBeach } from "../../lib/coverage";
import { advisoryProbabilityPresentation } from "../../lib/forecastPresentation";
import { daysSince, RISK_COLORS, riskAdvice, riskHead } from "../../lib/utils";
import { palette, bandColor } from "../../lib/theme";
import { DropRow, SeverityBar, type RiskBand } from "../../components/RiskSystem";

export default function ParentBeachScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [parent, setParent] = useState<ParentBeachSummary | null>(null);
  const [memberBeaches, setMemberBeaches] = useState<BeachSummary[]>([]);
  const [memberForecasts, setMemberForecasts] = useState<Record<string, ForecastRecord | null>>({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!id) return;
    const today = todayLA();

    getParentBeaches()
      .then(async (parents) => {
        const nextParent = findModeledBeach(parents, id);
        setParent(nextParent);
        if (!nextParent) return;

        const modeledMembers = filterModeledBeaches(await getBeaches()).filter((beach) =>
          nextParent.member_beach_ids.includes(beach.id)
        );
        const forecasts = await Promise.all(
          modeledMembers.map(async (beach) => {
            const forecast = await getForecast(beach.id, today).catch(() => null);
            return [beach.id, forecast] as [string, ForecastRecord | null];
          })
        );

        setMemberBeaches(modeledMembers);
        setMemberForecasts(Object.fromEntries(forecasts));
      })
      .finally(() => setLoading(false));
  }, [id]);

  if (loading) {
    return (
      <View style={{ flex: 1, justifyContent: "center", alignItems: "center", backgroundColor: palette.navy }}>
        <ActivityIndicator color={palette.bone} size="large" />
      </View>
    );
  }

  if (!parent) {
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

  const band = (parent.risk_band ?? "Moderate") as RiskBand;
  const colors = RISK_COLORS[band] ?? RISK_COLORS.Moderate;

  return (
    <View style={{ flex: 1, backgroundColor: palette.bone }}>
      <ScrollView contentContainerStyle={{ paddingBottom: 48 }}>
        <View style={[s.hero, { backgroundColor: colors.hero[0] }]}>
          <SafeAreaView edges={["top"]}>
            <View style={s.navRow}>
              <TouchableOpacity onPress={() => router.back()} style={s.backBtn}>
                <Feather name="chevron-left" size={20} color={palette.white} />
              </TouchableOpacity>
            </View>
            <Text style={s.heroSub}>{parent.county} County · {parent.region}</Text>
            <Text style={s.heroTitle}>{parent.name}</Text>
            <View style={s.heroMeta}>
              <Text style={s.heroMetaText}>
                {memberBeaches.length} forecast station{memberBeaches.length !== 1 ? "s" : ""}
              </Text>
              {parent.risk_band && (
                <View style={s.riskPill}>
                  <Text style={s.riskPillText}>
                    {parent.has_active_advisory ? "Official advisory active" : `${parent.risk_band} modeled risk`}
                  </Text>
                </View>
              )}
            </View>
            {parent.p_exceed != null && (
              <Text style={s.heroAdvice}>
                {parent.has_active_advisory
                  ? "Follow posted county guidance before entering."
                  : riskAdvice(band)}
              </Text>
            )}
          </SafeAreaView>
        </View>

        {parent.has_active_advisory && (
          <View style={{ padding: 16, paddingBottom: 0 }}>
            <View style={s.advisoryCard}>
              <Text style={s.advisoryTitle}>Official Advisory Active</Text>
              <Text style={s.advisoryBody}>
                An official county health advisory is currently active at this location.
              </Text>
            </View>
          </View>
        )}

        {parent.p_exceed != null && (
          <View style={{ padding: 16, paddingBottom: 0 }}>
            <Text style={s.sectionLabel}>Overall forecast</Text>
            <View style={[s.riskBanner, { backgroundColor: colors.bg }]}>
              <View style={{ flex: 1 }}>
                <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start" }}>
                  <View>
                    <Text style={[s.riskBandText, { color: colors.deep }]}>
                      {parent.has_active_advisory ? "Official advisory active." : riskHead(band)}
                    </Text>
                    <Text style={[s.riskAdviceText, { color: colors.deep }]}>
                      {parent.has_active_advisory
                        ? "This display is elevated by the official advisory."
                        : riskAdvice(band)}
                    </Text>
                  </View>
                  <View style={{ alignItems: "flex-end", gap: 6 }}>
                    <DropRow band={band} size={14} />
                    <Text style={[s.pctBig, { color: colors.deep }]}>
                      {Math.round(parent.p_exceed * 100)}
                      <Text style={{ fontSize: 14 }}>%</Text>
                    </Text>
                    <Text style={[s.pctSub, { color: colors.deep }]}>
                      {parent.has_active_advisory ? "advisory display" : "exceed chance"}
                    </Text>
                  </View>
                </View>
                <View style={{ marginTop: 12 }}>
                  <SeverityBar band={band} height={6} />
                </View>
              </View>
            </View>
          </View>
        )}

        <View style={{ padding: 16, paddingTop: 16 }}>
          <Text style={s.sectionLabel}>Forecast stations</Text>
          <View style={s.stationCard}>
            {memberBeaches.map((beach, index) => {
              const forecast = memberForecasts[beach.id];
              const stationBand = forecast?.risk_band ?? null;
              const stationColors = stationBand ? RISK_COLORS[stationBand] ?? RISK_COLORS.Moderate : null;
              const sampleAge = daysSince(beach.latest_official_sample_at);

              return (
                <TouchableOpacity
                  key={beach.id}
                  onPress={() => router.push(`/beach/${beach.id}` as any)}
                  style={[s.stationRow, index > 0 && { borderTopWidth: 1, borderTopColor: palette.lineSoft }]}
                  activeOpacity={0.7}
                >
                  {stationBand ? (
                    <DropRow band={stationBand} size={10} />
                  ) : (
                    <View style={[s.stationDot, { backgroundColor: palette.sand }]} />
                  )}
                  <View style={{ flex: 1 }}>
                    <Text style={s.stationName}>{beach.name}</Text>
                    <Text style={s.stationSub}>
                      {forecast
                        ? (() => {
                            const probability = advisoryProbabilityPresentation(forecast);
                            const value = probability.secondaryPercent ?? probability.primaryPercent;
                            const label = probability.secondaryLabel ? "model-only" : "exceed chance";
                            return `${value ?? "—"}% ${label}`;
                          })()
                        : "Forecast unavailable"}
                      {sampleAge != null
                        ? `  ·  sampled ${
                            sampleAge === 0 ? "today" : sampleAge === 1 ? "yesterday" : `${sampleAge}d ago`
                          }`
                        : ""}
                    </Text>
                  </View>
                  {stationBand && (
                    <Text style={[s.stationRisk, { color: bandColor(stationBand) }]}>
                      {stationBand}
                    </Text>
                  )}
                  <Feather name="chevron-right" size={16} color={palette.sand} />
                </TouchableOpacity>
              );
            })}
          </View>
        </View>
      </ScrollView>
    </View>
  );
}

const s = StyleSheet.create({
  hero: { padding: 20, paddingBottom: 28 },
  navRow: { flexDirection: "row", alignItems: "center", marginTop: 4 },
  backBtn: {
    width: 36, height: 36, borderRadius: 12,
    backgroundColor: "rgba(255,255,255,0.20)",
    alignItems: "center", justifyContent: "center",
  },
  heroSub: { color: "rgba(255,255,255,0.85)", fontSize: 11, fontWeight: "700", textTransform: "uppercase", letterSpacing: 1.2, marginTop: 22 },
  heroTitle: { color: palette.white, fontSize: 30, fontWeight: "700", marginTop: 4, lineHeight: 36, letterSpacing: -0.4 },
  heroMeta: { flexDirection: "row", alignItems: "center", gap: 10, marginTop: 10 },
  heroMetaText: { color: "rgba(255,255,255,0.85)", fontSize: 12, fontWeight: "500" },
  riskPill: { backgroundColor: "rgba(255,255,255,0.22)", paddingHorizontal: 10, paddingVertical: 4, borderRadius: 999 },
  riskPillText: { color: palette.white, fontSize: 11, fontWeight: "700", letterSpacing: 0.3 },
  heroAdvice: { color: "rgba(255,255,255,0.86)", fontSize: 13, lineHeight: 20, marginTop: 10, maxWidth: 320 },
  advisoryCard: { backgroundColor: "#fee2e2", padding: 16, borderRadius: 18, borderWidth: 1, borderColor: "#fca5a5" },
  advisoryTitle: { color: "#991b1b", fontWeight: "700", fontSize: 13, textTransform: "uppercase", letterSpacing: 0.5 },
  advisoryBody: { color: "#991b1b", marginTop: 4, fontSize: 15, lineHeight: 22 },
  sectionLabel: { fontSize: 11, fontWeight: "700", color: palette.muted, textTransform: "uppercase", letterSpacing: 1.2, marginBottom: 10 },
  riskBanner: { borderRadius: 18, padding: 16, flexDirection: "row", alignItems: "center", gap: 12 },
  riskBandText: { fontSize: 18, fontWeight: "700", letterSpacing: -0.2 },
  riskAdviceText: { fontSize: 12, marginTop: 3, lineHeight: 17 },
  pctBig: { fontSize: 26, fontWeight: "700", lineHeight: 30, letterSpacing: -0.3 },
  pctSub: { fontSize: 9, fontWeight: "600", opacity: 0.75 },
  stationCard: { backgroundColor: palette.white, borderRadius: 18, borderWidth: 1, borderColor: palette.lineSoft, overflow: "hidden" },
  stationRow: { flexDirection: "row", alignItems: "center", gap: 12, padding: 16 },
  stationDot: { width: 10, height: 10, borderRadius: 5, flexShrink: 0 },
  stationName: { fontSize: 14, fontWeight: "600", color: palette.ink },
  stationSub: { fontSize: 11, color: palette.muted, marginTop: 2 },
  stationRisk: { fontSize: 11, fontWeight: "700", letterSpacing: 0.3 },
});
