import { useEffect, useState } from "react";
import { View, Text, TextInput, TouchableOpacity, ScrollView, StyleSheet, ActivityIndicator, Image } from "react-native";
import { useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import * as Location from "expo-location";
import { getParentBeaches, getSystemHealth, type ParentBeachSummary, type SystemHealthResponse } from "../../lib/api";
import { RISK_COLORS } from "../../lib/utils";
import { DropRow, SeverityBar, RISK_COPY, type RiskBand } from "../../components/RiskSystem";

function distanceKm(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const R = 6371;
  const dLat = (lat2 - lat1) * (Math.PI / 180);
  const dLon = (lon2 - lon1) * (Math.PI / 180);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(lat1 * (Math.PI / 180)) * Math.cos(lat2 * (Math.PI / 180)) * Math.sin(dLon / 2) ** 2;
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

function fmtDist(km: number): string {
  const mi = km * 0.621371;
  return mi < 10 ? `${mi.toFixed(1)} mi` : `${Math.round(mi)} mi`;
}

export default function HomeTab() {
  const [beaches, setBeaches] = useState<ParentBeachSummary[]>([]);
  const [health, setHealth] = useState<SystemHealthResponse | null>(null);
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(true);
  const [userCoords, setUserCoords] = useState<{ lat: number; lon: number } | null>(null);
  const router = useRouter();

  useEffect(() => {
    Promise.all([
      getParentBeaches(),
      getSystemHealth().catch(() => null),
    ]).then(([bs, h]) => {
      setBeaches(bs);
      setHealth(h);
    }).finally(() => setLoading(false));

    Location.requestForegroundPermissionsAsync().then(({ status }) => {
      if (status === "granted") {
        Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced })
          .then((loc) => setUserCoords({ lat: loc.coords.latitude, lon: loc.coords.longitude }))
          .catch(() => {});
      }
    });
  }, []);

  const sorted = userCoords
    ? [...beaches].sort(
        (a, b) =>
          distanceKm(userCoords.lat, userCoords.lon, a.geometry.latitude, a.geometry.longitude) -
          distanceKm(userCoords.lat, userCoords.lon, b.geometry.latitude, b.geometry.longitude)
      )
    : beaches;

  const results = q
    ? sorted.filter(
        (b) =>
          b.name.toLowerCase().includes(q.toLowerCase()) ||
          b.county.toLowerCase().includes(q.toLowerCase())
      ).slice(0, 20)
    : sorted.slice(0, 10);

  const nearest = !q && sorted.length > 0 ? sorted[0] : null;
  const nearestBand = nearest?.risk_band as RiskBand | undefined;
  const nearestColors = nearestBand ? RISK_COLORS[nearestBand] : null;

  function pick(b: ParentBeachSummary) {
    if (b.station_count > 1) {
      router.push(`/parent/${b.id}` as any);
    } else {
      router.push(`/beach/${b.member_beach_ids[0]}` as any);
    }
  }

  return (
    <View style={s.root}>
      {/* Hero header */}
      <View style={s.hero}>
        <SafeAreaView edges={["top"]}>
          {/* Sun + wave decorative SVG-equivalent using Views */}
          <View style={s.sunDecor} />
          <View style={s.waveDecor} />

          <View style={s.brand}>
            <Image source={require('../../assets/icon.png')} style={{width: 20, height: 20, marginRight: 8}} resizeMode="contain" />
            <Text style={s.brandMark}>SHORELIFE</Text>
          </View>

          {!loading && nearest && nearestColors && nearestBand ? (
            /* Nearest beach hero card */
            <TouchableOpacity onPress={() => pick(nearest)} style={s.nearestCard} activeOpacity={0.85}>
              <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start" }}>
                <View style={{ flex: 1 }}>
                  <Text style={s.nearestEyebrow}>Can I swim today?</Text>
                  <Text style={s.nearestVerdict}>{RISK_COPY[nearestBand].head}</Text>
                  <Text style={s.nearestSub}>{RISK_COPY[nearestBand].sub}</Text>
                </View>
                <DropRow band={nearestBand} size={15} />
              </View>
              <View style={{ marginTop: 12 }}>
                <SeverityBar band={nearestBand} height={5} />
              </View>
              <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginTop: 10 }}>
                <Text style={s.nearestBeachName}>{nearest.name}</Text>
                {userCoords && (
                  <Text style={s.nearestDist}>
                    {fmtDist(distanceKm(userCoords.lat, userCoords.lon, nearest.geometry.latitude, nearest.geometry.longitude))}
                  </Text>
                )}
              </View>
            </TouchableOpacity>
          ) : !loading ? (
            <View style={{ marginTop: 24 }}>
              <Text style={s.headline}>Know before{"\n"}you paddle out.</Text>
              <Text style={s.sub}>Daily bacteria + surf forecast for California beaches.</Text>
            </View>
          ) : null}

          {nearest && nearest.has_active_advisory && (
            <View style={s.advisoryBanner}>
              <Text style={s.advisoryText}>
                ⚠ ACTIVE ADVISORY AT NEAREST BEACH
              </Text>
            </View>
          )}
        </SafeAreaView>
      </View>

      {/* Sheet */}
      <View style={s.sheet}>
        <View style={s.searchBox}>
          <Text style={s.searchIcon}>🔍</Text>
          <TextInput
            style={s.searchInput}
            value={q}
            onChangeText={setQ}
            placeholder="Search beaches, cities, counties"
            placeholderTextColor="#94a3b8"
            clearButtonMode="while-editing"
          />
        </View>

        {loading ? (
          <ActivityIndicator style={{ marginTop: 24 }} color="#0b4266" />
        ) : (
          <ScrollView style={{ marginTop: 14 }} keyboardShouldPersistTaps="handled">
            <Text style={s.sectionLabel}>
              {q ? "Results" : userCoords ? "Nearby beaches" : "California beaches"}
            </Text>
            {results.map((b, idx) => {
              const band = b.risk_band as RiskBand | null;
              const dist = userCoords && !q
                ? distanceKm(userCoords.lat, userCoords.lon, b.geometry.latitude, b.geometry.longitude)
                : null;
              const colors = band ? RISK_COLORS[band] : null;
              const dotColor = colors?.hero[0] ?? "#94a3b8";
              return (
                <TouchableOpacity key={b.id} onPress={() => pick(b)} style={s.beachRow} activeOpacity={0.7}>
                  {band ? (
                    <DropRow band={band} size={11} />
                  ) : (
                    <View style={[s.dot, { backgroundColor: "#94a3b8" }]} />
                  )}
                  <View style={{ flex: 1 }}>
                    <View style={{ flexDirection: "row", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                      <Text style={s.beachName}>{b.name}</Text>
                      {b.has_active_advisory && <Text style={s.advisoryDot}>⚠</Text>}
                      {b.station_count > 1 && (
                        <Text style={s.stationBadge}>{b.station_count} stations</Text>
                      )}
                    </View>
                    <Text style={s.beachSub}>
                      {b.county} County{dist != null ? ` · ${fmtDist(dist)}` : ` · ${b.region}`}
                    </Text>
                  </View>
                  {band && (
                    <Text style={[s.riskLabel, { color: dotColor }]}>{band}</Text>
                  )}
                  <Text style={s.chevron}>›</Text>
                </TouchableOpacity>
              );
            })}
            {q && results.length === 0 && (
              <Text style={s.noResults}>No matches — try another search.</Text>
            )}
            <View style={{ height: 40 }} />
          </ScrollView>
        )}
      </View>
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: "#0b4266" },
  hero: { padding: 22, paddingBottom: 28, position: "relative", overflow: "hidden" },
  sunDecor: {
    position: "absolute", top: 0, right: 20, width: 80, height: 80,
    borderRadius: 40, backgroundColor: "rgba(255,255,255,0.1)",
  },
  waveDecor: {
    position: "absolute", bottom: 0, left: 0, right: 0, height: 20,
    backgroundColor: "rgba(255,255,255,0.07)", borderTopLeftRadius: 60, borderTopRightRadius: 60,
  },
  brand: { flexDirection: "row", alignItems: "center", marginTop: 8 },
  brandMark: { color: "rgba(255,255,255,0.9)", fontSize: 12, fontWeight: "800", letterSpacing: 3 },
  nearestCard: {
    marginTop: 18, backgroundColor: "rgba(255,255,255,0.18)",
    borderRadius: 20, padding: 18, borderWidth: 1, borderColor: "rgba(255,255,255,0.12)",
    shadowColor: "#000", shadowOffset: { width: 0, height: 10 }, shadowOpacity: 0.1, shadowRadius: 20,
  },
  nearestEyebrow: {
    fontSize: 9, fontWeight: "700", color: "rgba(255,255,255,0.7)",
    textTransform: "uppercase", letterSpacing: 1.2,
  },
  nearestVerdict: { fontSize: 44, fontWeight: "400", color: "#fff", lineHeight: 48, marginTop: 4 },
  nearestSub: { fontSize: 14, color: "rgba(255,255,255,0.9)", marginTop: 6, lineHeight: 19 },
  nearestBeachName: { fontSize: 13, fontWeight: "600", color: "rgba(255,255,255,0.85)" },
  nearestDist: { fontSize: 12, color: "rgba(255,255,255,0.6)", fontFamily: "System" },
  headline: { color: "#fff", fontSize: 34, fontWeight: "700", lineHeight: 40, marginTop: 24 },
  sub: { color: "rgba(255,255,255,0.8)", fontSize: 14, marginTop: 10, lineHeight: 20 },
  advisoryBanner: {
    marginTop: 14, backgroundColor: "rgba(239,68,68,0.25)",
    paddingVertical: 7, paddingHorizontal: 12, borderRadius: 8, alignSelf: "flex-start",
  },
  advisoryText: { color: "#fca5a5", fontWeight: "700", fontSize: 11, letterSpacing: 0.5 },
  sheet: {
    flex: 1, backgroundColor: "#faf6ee", // bone
    borderTopLeftRadius: 28, borderTopRightRadius: 28,
    padding: 20,
    shadowColor: "#000", shadowOffset: { width: 0, height: -12 },
    shadowOpacity: 0.1, shadowRadius: 24,
  },
  searchBox: {
    flexDirection: "row", alignItems: "center", gap: 10,
    backgroundColor: "#e8dfcc", // sand
    borderRadius: 14, paddingHorizontal: 14, paddingVertical: 12,
  },
  searchIcon: { fontSize: 15 },
  searchInput: { flex: 1, fontSize: 15, color: "#1a2730" },
  sectionLabel: {
    fontSize: 10, fontWeight: "700", color: "#5e6b73",
    textTransform: "uppercase", letterSpacing: 1.2, marginBottom: 10, marginTop: 2,
  },
  beachRow: {
    flexDirection: "row", alignItems: "center", gap: 12,
    paddingVertical: 14, borderBottomWidth: 1, borderBottomColor: "#d6cbb1",
  },
  dot: { width: 8, height: 8, borderRadius: 4 },
  beachName: { fontSize: 15, fontWeight: "600", color: "#1a2730" },
  advisoryDot: { fontSize: 10 },
  stationBadge: { fontSize: 9, color: "#5e6b73", fontWeight: "600", letterSpacing: 0.3 },
  beachSub: { fontSize: 12, color: "#5e6b73", marginTop: 2 },
  riskLabel: { fontSize: 10, fontWeight: "700", letterSpacing: 0.3, textTransform: "uppercase" },
  chevron: { fontSize: 20, color: "#d6cbb1", fontWeight: "300" },
  noResults: { fontSize: 13, color: "#5e6b73", padding: 12 },
});
