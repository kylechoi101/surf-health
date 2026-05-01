import { useEffect, useState } from "react";
import { ActivityIndicator, ScrollView, StyleSheet, Text, TouchableOpacity, View } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
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
import { daysSince, RISK_COLORS, riskAdvice, riskHead } from "../../lib/utils";
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
      <View style={{ flex: 1, justifyContent: "center", alignItems: "center", backgroundColor: "#0b4266" }}>
        <ActivityIndicator color="#fff" size="large" />
      </View>
    );
  }

  if (!parent) {
    return (
      <SafeAreaView style={{ flex: 1, justifyContent: "center", alignItems: "center" }}>
        <Text style={{ fontSize: 16, color: "#64748b" }}>Beach not found</Text>
        <TouchableOpacity onPress={() => router.back()} style={{ marginTop: 16 }}>
          <Text style={{ color: "#0b4266", fontWeight: "600" }}>← Go back</Text>
        </TouchableOpacity>
      </SafeAreaView>
    );
  }

  const band = (parent.risk_band ?? "Moderate") as RiskBand;
  const colors = RISK_COLORS[band] ?? RISK_COLORS.Moderate;

  return (
    <View style={{ flex: 1 }}>
      <ScrollView contentContainerStyle={{ paddingBottom: 48 }}>
        <View style={[s.hero, { backgroundColor: colors.hero[0] }]}>
          <SafeAreaView edges={["top"]}>
            <View style={s.navRow}>
              <TouchableOpacity onPress={() => router.back()} style={s.backBtn}>
                <Text style={s.backText}>‹</Text>
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
                  <Text style={s.riskPillText}>{parent.risk_band} risk</Text>
                </View>
              )}
            </View>
            {parent.p_exceed != null && <Text style={s.heroAdvice}>{riskAdvice(band)}</Text>}
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
                    <Text style={[s.riskBandText, { color: colors.deep }]}>{riskHead(band)}</Text>
                    <Text style={[s.riskAdviceText, { color: colors.deep }]}>{riskAdvice(band)}</Text>
                  </View>
                  <View style={{ alignItems: "flex-end", gap: 6 }}>
                    <DropRow band={band} size={14} />
                    <Text style={[s.pctBig, { color: colors.deep }]}>
                      {Math.round(parent.p_exceed * 100)}
                      <Text style={{ fontSize: 14 }}>%</Text>
                    </Text>
                    <Text style={[s.pctSub, { color: colors.deep }]}>exceed chance</Text>
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
                  style={[s.stationRow, index > 0 && { borderTopWidth: 1, borderTopColor: "#f1f5f9" }]}
                >
                  <View style={[s.stationDot, { backgroundColor: stationColors?.hero[0] ?? "#94a3b8" }]} />
                  <View style={{ flex: 1 }}>
                    <Text style={s.stationName}>{beach.name}</Text>
                    <Text style={s.stationSub}>
                      {forecast ? `${Math.round(forecast.p_exceed * 100)}% exceed chance` : "Forecast unavailable"}
                      {sampleAge != null
                        ? ` · sampled ${
                            sampleAge === 0 ? "today" : sampleAge === 1 ? "yesterday" : `${sampleAge}d ago`
                          }`
                        : ""}
                    </Text>
                  </View>
                  {stationBand && (
                    <Text style={[s.stationRisk, { color: stationColors?.hero[0] ?? "#64748b" }]}>
                      {stationBand}
                    </Text>
                  )}
                  <Text style={s.chevron}>›</Text>
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
  backBtn: { padding: 4 },
  backText: { color: "#fff", fontSize: 28, lineHeight: 32, fontWeight: "300" },
  heroSub: { color: "rgba(255,255,255,0.8)", fontSize: 11, fontWeight: "600", textTransform: "uppercase", letterSpacing: 1, marginTop: 20 },
  heroTitle: { color: "#fff", fontSize: 28, fontWeight: "700", marginTop: 4, lineHeight: 34 },
  heroMeta: { flexDirection: "row", alignItems: "center", gap: 10, marginTop: 10 },
  heroMetaText: { color: "rgba(255,255,255,0.85)", fontSize: 12, fontWeight: "500" },
  riskPill: { backgroundColor: "rgba(255,255,255,0.25)", paddingHorizontal: 10, paddingVertical: 4, borderRadius: 20 },
  riskPillText: { color: "#fff", fontSize: 11, fontWeight: "700" },
  heroAdvice: { color: "rgba(255,255,255,0.85)", fontSize: 13, lineHeight: 20, marginTop: 10 },
  advisoryCard: { backgroundColor: "#fee2e2", padding: 16, borderRadius: 18, borderWidth: 1, borderColor: "#fca5a5" },
  advisoryTitle: { color: "#991b1b", fontWeight: "700", fontSize: 13, textTransform: "uppercase", letterSpacing: 0.5 },
  advisoryBody: { color: "#991b1b", marginTop: 4, fontSize: 15, lineHeight: 22 },
  sectionLabel: { fontSize: 11, fontWeight: "700", color: "#64748b", textTransform: "uppercase", letterSpacing: 1, marginBottom: 10 },
  riskBanner: { borderRadius: 18, padding: 16, flexDirection: "row", alignItems: "center", gap: 12 },
  riskBandText: { fontSize: 18, fontWeight: "700" },
  riskAdviceText: { fontSize: 12, marginTop: 3, lineHeight: 17 },
  pctBig: { fontSize: 26, fontWeight: "700", lineHeight: 30 },
  pctSub: { fontSize: 9, fontWeight: "600", opacity: 0.75 },
  stationCard: { backgroundColor: "#fff", borderRadius: 18, borderWidth: 1, borderColor: "#e5e7eb", overflow: "hidden" },
  stationRow: { flexDirection: "row", alignItems: "center", gap: 12, padding: 16 },
  stationDot: { width: 10, height: 10, borderRadius: 5, flexShrink: 0 },
  stationName: { fontSize: 14, fontWeight: "600", color: "#0f172a" },
  stationSub: { fontSize: 11, color: "#64748b", marginTop: 2 },
  stationRisk: { fontSize: 11, fontWeight: "700", letterSpacing: 0.3 },
  chevron: { fontSize: 20, color: "#cbd5e1", fontWeight: "300" },
});
