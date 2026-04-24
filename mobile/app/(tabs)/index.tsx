import { useEffect, useState } from "react";
import { View, Text, TextInput, TouchableOpacity, ScrollView, StyleSheet, ActivityIndicator } from "react-native";
import { useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import * as Location from "expo-location";
import { getBeaches, type BeachSummary } from "../../lib/api";

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
  const [beaches, setBeaches] = useState<BeachSummary[]>([]);
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(true);
  const [userCoords, setUserCoords] = useState<{ lat: number; lon: number } | null>(null);
  const router = useRouter();

  useEffect(() => {
    getBeaches().then(setBeaches).finally(() => setLoading(false));

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
    ? sorted
        .filter(
          (b) =>
            b.name.toLowerCase().includes(q.toLowerCase()) ||
            b.county.toLowerCase().includes(q.toLowerCase())
        )
        .slice(0, 10)
    : sorted.slice(0, 5);

  function pick(b: BeachSummary) {
    router.push(`/beach/${b.id}` as any);
  }

  return (
    <View style={s.root}>
      <View style={s.hero}>
        <SafeAreaView edges={["top"]}>
          <View style={s.brand}>
            <Text style={s.brandMark}>〰️ Surf Health</Text>
          </View>
          <Text style={s.headline}>
            Find out if the water&apos;s clean{" "}
            <Text style={{ opacity: 0.7 }}>— before you paddle out.</Text>
          </Text>
          <Text style={s.sub}>Daily bacteria + surf forecast for 290+ California beaches.</Text>

          {health && health.active_advisories_count !== undefined && health.active_advisories_count > 0 && (
            <View style={{ marginTop: 16, backgroundColor: "rgba(0,0,0,0.1)", paddingVertical: 8, paddingHorizontal: 12, borderRadius: 8, alignSelf: "flex-start" }}>
              <Text style={{ color: "#000", fontWeight: "700", fontSize: 12, letterSpacing: 0.5, textTransform: "uppercase" }}>
                {health.active_advisories_count} ADVISOR{health.active_advisories_count === 1 ? "Y" : "IES"} ACROSS CALIFORNIA TODAY
              </Text>
            </View>
          )}
        </SafeAreaView>
      </View>

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
          <ScrollView style={{ marginTop: 16 }} keyboardShouldPersistTaps="handled">
            {!q && (
              <Text style={s.sectionLabel}>
                {userCoords ? "Nearest beaches" : "Nearby beaches"}
              </Text>
            )}
            {results.map((b) => {
              const dist =
                userCoords && !q
                  ? distanceKm(userCoords.lat, userCoords.lon, b.geometry.latitude, b.geometry.longitude)
                  : null;
              return (
                <TouchableOpacity key={b.id} onPress={() => pick(b)} style={s.beachRow}>
                  <View style={s.dot} />
                  <View style={{ flex: 1 }}>
                    <Text style={s.beachName}>{b.name}</Text>
                    <Text style={s.beachSub}>
                      {b.county} County
                      {dist != null ? ` · ${fmtDist(dist)}` : ` · ${b.region}`}
                    </Text>
                  </View>
                  <Text style={s.chevron}>›</Text>
                </TouchableOpacity>
              );
            })}
            {q && results.length === 0 && (
              <Text style={s.noResults}>No matches — try another search.</Text>
            )}
          </ScrollView>
        )}
      </View>
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: "#0b4266" },
  hero: { padding: 22, paddingBottom: 32 },
  brand: { flexDirection: "row", alignItems: "center", marginTop: 8 },
  brandMark: { color: "#fff", fontSize: 14, fontWeight: "700", letterSpacing: 1 },
  headline: { color: "#fff", fontSize: 32, fontWeight: "700", lineHeight: 38, marginTop: 28, maxWidth: 300 },
  sub: { color: "rgba(255,255,255,0.8)", fontSize: 15, marginTop: 12, lineHeight: 22 },
  sheet: {
    flex: 1, backgroundColor: "#fff",
    borderTopLeftRadius: 28, borderTopRightRadius: 28,
    padding: 22,
    shadowColor: "#000", shadowOffset: { width: 0, height: -12 },
    shadowOpacity: 0.15, shadowRadius: 24,
  },
  searchBox: {
    flexDirection: "row", alignItems: "center", gap: 10,
    backgroundColor: "#f1f5f9", borderRadius: 14, paddingHorizontal: 14, paddingVertical: 12,
  },
  searchIcon: { fontSize: 16 },
  searchInput: { flex: 1, fontSize: 15, color: "#0f172a" },
  sectionLabel: {
    fontSize: 11, fontWeight: "700", color: "#64748b",
    textTransform: "uppercase", letterSpacing: 1, marginBottom: 8,
  },
  beachRow: {
    flexDirection: "row", alignItems: "center", gap: 12,
    paddingVertical: 11, borderBottomWidth: 1, borderBottomColor: "#f8fafc",
  },
  dot: { width: 8, height: 8, borderRadius: 4, backgroundColor: "#94a3b8" },
  beachName: { fontSize: 14, fontWeight: "600", color: "#0f172a" },
  beachSub: { fontSize: 11, color: "#64748b", marginTop: 2 },
  chevron: { fontSize: 20, color: "#cbd5e1", fontWeight: "300" },
  noResults: { fontSize: 13, color: "#64748b", padding: 12 },
});
