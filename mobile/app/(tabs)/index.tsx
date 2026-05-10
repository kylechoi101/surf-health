import { useEffect, useState } from "react";
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  ScrollView,
  StyleSheet,
  ActivityIndicator,
  Image,
} from "react-native";
import { useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import * as Location from "expo-location";
import { Feather } from "@expo/vector-icons";
import {
  getParentBeaches,
  getSystemHealth,
  type ParentBeachSummary,
  type SystemHealthResponse,
} from "../../lib/api";
import { filterModeledBeaches } from "../../lib/coverage";
import {
  palette,
  radius,
  shadows,
  space,
  typography,
  bandColor,
} from "../../lib/theme";
import {
  DropRow,
  SeverityBar,
  RISK_COPY,
  type RiskBand,
} from "../../components/RiskSystem";
import { BetaNotice } from "../../components/BetaNotice";

function distanceKm(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const R = 6371;
  const dLat = (lat2 - lat1) * (Math.PI / 180);
  const dLon = (lon2 - lon1) * (Math.PI / 180);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(lat1 * (Math.PI / 180)) *
      Math.cos(lat2 * (Math.PI / 180)) *
      Math.sin(dLon / 2) ** 2;
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

function fmtDist(km: number): string {
  const mi = km * 0.621371;
  return mi < 10 ? `${mi.toFixed(1)} mi` : `${Math.round(mi)} mi`;
}

export default function HomeTab() {
  const [beaches, setBeaches] = useState<ParentBeachSummary[]>([]);
  const [, setHealth] = useState<SystemHealthResponse | null>(null);
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(true);
  const [userCoords, setUserCoords] = useState<{ lat: number; lon: number } | null>(null);
  const router = useRouter();

  useEffect(() => {
    Promise.all([getParentBeaches(), getSystemHealth().catch(() => null)])
      .then(([bs, h]) => {
        setBeaches(filterModeledBeaches(bs));
        setHealth(h);
      })
      .finally(() => setLoading(false));

    Location.requestForegroundPermissionsAsync().then(({ status }) => {
      if (status === "granted") {
        Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced })
          .then((loc) =>
            setUserCoords({ lat: loc.coords.latitude, lon: loc.coords.longitude })
          )
          .catch(() => {});
      }
    });
  }, []);

  const sorted = userCoords
    ? [...beaches].sort(
        (a, b) =>
          distanceKm(
            userCoords.lat,
            userCoords.lon,
            a.geometry.latitude,
            a.geometry.longitude
          ) -
          distanceKm(
            userCoords.lat,
            userCoords.lon,
            b.geometry.latitude,
            b.geometry.longitude
          )
      )
    : beaches;

  const results = q
    ? sorted
        .filter(
          (b) =>
            b.name.toLowerCase().includes(q.toLowerCase()) ||
            b.county.toLowerCase().includes(q.toLowerCase())
        )
        .slice(0, 20)
    : sorted.slice(0, 10);

  const nearest = !q && sorted.length > 0 ? sorted[0] : null;
  const nearestBand = nearest?.risk_band as RiskBand | undefined;

  function pick(b: ParentBeachSummary) {
    if (b.station_count > 1) {
      router.push(`/parent/${b.id}` as any);
    } else {
      router.push(`/beach/${b.member_beach_ids[0]}` as any);
    }
  }

  return (
    <View style={s.root}>
      {/* Hero */}
      <View style={s.hero}>
        {/* Decorative layered translucent disks (sun) */}
        <View style={s.disk1} pointerEvents="none" />
        <View style={s.disk2} pointerEvents="none" />
        <View style={s.diskGlow} pointerEvents="none" />
        {/* Soft horizon line */}
        <View style={s.diskGlow} pointerEvents="none" />
            {/* Removed white line under icon */}

        <SafeAreaView edges={["top"]}>
          <View style={s.brand}>
            <Image
              source={require("../../assets/lockup.png")}
              style={{ height: 26, aspectRatio: 2, marginRight: 10 }}
              resizeMode="contain"
            />
            <Text style={s.brandMark}>SHORELIFE</Text>
          </View>

          {!loading && nearest && nearestBand ? (
            <TouchableOpacity
              onPress={() => pick(nearest)}
              style={s.nearestCard}
              activeOpacity={0.88}
            >
              <View style={s.nearestTopRow}>
                <View style={{ flex: 1 }}>
                  <Text style={s.nearestEyebrow}>Today&apos;s modeled risk</Text>
                  <View style={{ marginTop: 6 }}>
                    <BetaNotice isBeta={true} />
                  </View>
                  <Text style={s.nearestVerdict}>
                    {RISK_COPY[nearestBand].head}
                  </Text>
                  <Text style={s.nearestSub}>{RISK_COPY[nearestBand].sub}</Text>
                </View>
                <DropRow band={nearestBand} size={15} />
              </View>
              <View style={{ marginTop: space.md }}>
                <SeverityBar band={nearestBand} height={5} />
              </View>
              <View style={s.nearestFooter}>
                <Text style={s.nearestBeachName} numberOfLines={1}>
                  {nearest.name}
                </Text>
                <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
                  {userCoords && (
                    <Text style={s.nearestDist}>
                      {fmtDist(
                        distanceKm(
                          userCoords.lat,
                          userCoords.lon,
                          nearest.geometry.latitude,
                          nearest.geometry.longitude
                        )
                      )}
                    </Text>
                  )}
                  <Feather
                    name="chevron-right"
                    size={14}
                    color="rgba(255,255,255,0.7)"
                  />
                </View>
              </View>
            </TouchableOpacity>
          ) : !loading ? (
            <View style={{ marginTop: 24 }}>
              <Text style={s.headline}>Know before{"\n"}you paddle out.</Text>
              <Text style={s.sub}>
                Daily bacteria + surf forecast for California beaches.
              </Text>
            </View>
          ) : null}

          {nearest && nearest.has_active_advisory && (
            <View style={s.advisoryBanner}>
              <Feather name="alert-triangle" size={11} color="#fca5a5" />
              <Text style={s.advisoryText}>
                ACTIVE ADVISORY AT NEAREST BEACH
              </Text>
            </View>
          )}
        </SafeAreaView>
      </View>

      {/* Sheet */}
      <View style={s.sheet}>
        <View style={s.searchBox}>
          <Feather name="search" size={16} color={palette.muted} />
          <TextInput
            style={s.searchInput}
            value={q}
            onChangeText={setQ}
            placeholder="Search beaches, cities, counties"
            placeholderTextColor={palette.muted}
            clearButtonMode="while-editing"
          />
        </View>

        {loading ? (
          <ActivityIndicator
            style={{ marginTop: 24 }}
            color={palette.navy}
          />
        ) : (
          <ScrollView
            style={{ marginTop: space.md }}
            keyboardShouldPersistTaps="handled"
            showsVerticalScrollIndicator={false}
          >
            <Text style={s.sectionLabel}>
              {q ? "Results" : userCoords ? "Nearby beaches" : "California beaches"}
            </Text>
            {results.map((b) => {
              const band = b.risk_band as RiskBand | null;
              const dist =
                userCoords && !q
                  ? distanceKm(
                      userCoords.lat,
                      userCoords.lon,
                      b.geometry.latitude,
                      b.geometry.longitude
                    )
                  : null;
              return (
                <TouchableOpacity
                  key={b.id}
                  onPress={() => pick(b)}
                  style={s.beachRow}
                  activeOpacity={0.65}
                >
                  {band ? (
                    <DropRow band={band} size={11} />
                  ) : (
                    <View style={s.dotInactive} />
                  )}
                  <View style={{ flex: 1 }}>
                    <View style={s.beachNameRow}>
                      <Text style={s.beachName} numberOfLines={1}>
                        {b.name}
                      </Text>
                      {b.has_active_advisory && (
                        <Feather
                          name="alert-triangle"
                          size={11}
                          color="#b91c1c"
                          style={{ marginLeft: 6 }}
                        />
                      )}
                      {b.station_count > 1 && (
                        <Text style={s.stationBadge}>
                          {b.station_count} stations
                        </Text>
                      )}
                    </View>
                    <Text style={s.beachSub}>
                      {b.county} County
                      {dist != null ? `  ·  ${fmtDist(dist)}` : `  ·  ${b.region}`}
                    </Text>
                  </View>
                  {band && (
                    <Text
                      style={[s.riskLabel, { color: bandColor(band) }]}
                    >
                      {band}
                    </Text>
                  )}
                  <Feather
                    name="chevron-right"
                    size={16}
                    color={palette.sand}
                  />
                </TouchableOpacity>
              );
            })}
            {q && results.length === 0 && (
              <View style={s.noResultsWrap}>
                <Text style={s.noResultsTitle}>No matches</Text>
                <Text style={s.noResultsSub}>Try another search.</Text>
              </View>
            )}
            <View style={{ height: 60 }} />
          </ScrollView>
        )}
      </View>
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: palette.navy },

  hero: {
    paddingHorizontal: space.xl,
    paddingTop: space.sm,
    paddingBottom: space.xxl,
    position: "relative",
    overflow: "hidden",
  },
  // Layered decorative disks (warm sun-glow effect)
  disk1: {
    position: "absolute",
    top: -90,
    right: -80,
    width: 280,
    height: 280,
    borderRadius: 140,
    backgroundColor: "rgba(232,179,65,0.10)",
  },
  disk2: {
    position: "absolute",
    top: -40,
    right: -30,
    width: 180,
    height: 180,
    borderRadius: 90,
    backgroundColor: "rgba(232,179,65,0.13)",
  },
  diskGlow: {
    position: "absolute",
    top: 10,
    right: 30,
    width: 90,
    height: 90,
    borderRadius: 45,
    backgroundColor: "rgba(255,255,255,0.07)",
  },
  // Removed white line under icon

  brand: { flexDirection: "row", alignItems: "center", marginTop: 6 },
  brandLogoWrap: {
    height: 26,
    aspectRatio: 1.85,
    marginRight: 10,
    borderRadius: 6,
    overflow: "hidden",
    backgroundColor: "transparent",
  },
  brandLogo: {
    width: "100%",
    height: "100%",
  },
  brandMark: {
    color: "rgba(255,255,255,0.92)",
    fontSize: 12,
    fontWeight: "800",
    letterSpacing: 3.2,
  },

  nearestCard: {
    marginTop: 22,
    backgroundColor: "rgba(255,255,255,0.14)",
    borderRadius: radius.xl,
    padding: 18,
    borderWidth: 1,
    borderColor: "rgba(255,255,255,0.18)",
    ...shadows.hero,
    shadowOpacity: 0.18,
  },
  nearestTopRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "flex-start",
  },
  nearestEyebrow: {
    fontSize: 9,
    fontWeight: "700",
    color: "rgba(255,255,255,0.68)",
    textTransform: "uppercase",
    letterSpacing: 1.4,
  },
  nearestVerdict: {
    fontSize: 42,
    fontWeight: "700",
    color: palette.white,
    lineHeight: 46,
    letterSpacing: -0.4,
    marginTop: 4,
  },
  nearestSub: {
    fontSize: 14,
    color: "rgba(255,255,255,0.86)",
    marginTop: 6,
    lineHeight: 20,
    maxWidth: 280,
  },
  nearestFooter: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginTop: 12,
  },
  nearestBeachName: {
    flex: 1,
    fontSize: 13,
    fontWeight: "600",
    color: "rgba(255,255,255,0.92)",
    marginRight: 12,
  },
  nearestDist: {
    fontSize: 12,
    color: "rgba(255,255,255,0.62)",
    fontWeight: "500",
  },

  headline: {
    color: palette.white,
    fontSize: 34,
    fontWeight: "700",
    lineHeight: 40,
    letterSpacing: -0.4,
    marginTop: 28,
  },
  sub: {
    color: "rgba(255,255,255,0.78)",
    fontSize: 14,
    marginTop: 10,
    lineHeight: 20,
  },

  advisoryBanner: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    marginTop: 14,
    backgroundColor: "rgba(239,68,68,0.22)",
    paddingVertical: 7,
    paddingHorizontal: 11,
    borderRadius: radius.sm,
    alignSelf: "flex-start",
  },
  advisoryText: {
    color: "#fca5a5",
    fontWeight: "700",
    fontSize: 11,
    letterSpacing: 0.6,
  },

  sheet: {
    flex: 1,
    backgroundColor: palette.bone,
    borderTopLeftRadius: 28,
    borderTopRightRadius: 28,
    paddingHorizontal: space.xl,
    paddingTop: space.xl,
    ...shadows.sheet,
  },
  searchBox: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    backgroundColor: palette.ecruDeep,
    borderRadius: radius.md,
    paddingHorizontal: space.md,
    paddingVertical: 11,
  },
  searchInput: { flex: 1, fontSize: 15, color: palette.ink },

  sectionLabel: {
    ...typography.eyebrow,
    color: palette.muted,
    marginBottom: 10,
    marginTop: 2,
  },

  beachRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: space.md,
    paddingVertical: 14,
    borderBottomWidth: 1,
    borderBottomColor: palette.lineSoft,
  },
  dotInactive: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: palette.sand,
  },
  beachNameRow: { flexDirection: "row", alignItems: "center", flexWrap: "wrap" },
  beachName: { fontSize: 15, fontWeight: "600", color: palette.ink },
  stationBadge: {
    fontSize: 9,
    color: palette.muted,
    fontWeight: "700",
    letterSpacing: 0.5,
    marginLeft: 8,
    textTransform: "uppercase",
  },
  beachSub: { fontSize: 12, color: palette.muted, marginTop: 2 },
  riskLabel: {
    fontSize: 10,
    fontWeight: "700",
    letterSpacing: 0.4,
    textTransform: "uppercase",
  },

  noResultsWrap: { padding: 32, alignItems: "center" },
  noResultsTitle: { fontSize: 15, fontWeight: "600", color: palette.ink },
  noResultsSub: { fontSize: 13, color: palette.muted, marginTop: 4 },
});
