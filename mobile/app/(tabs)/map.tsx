import { useEffect, useMemo, useRef, useState } from "react";
import {
  View,
  Text,
  TouchableOpacity,
  StyleSheet,
  ActivityIndicator,
} from "react-native";
import { useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import MapView, { Marker, PROVIDER_DEFAULT } from "react-native-maps";
import { Feather } from "@expo/vector-icons";
import { getParentBeaches, type ParentBeachSummary } from "../../lib/api";
import { filterModeledBeaches } from "../../lib/coverage";
import {
  palette,
  radius,
  shadows,
  space,
  typography,
  bandColor,
} from "../../lib/theme";
import { DropRow, type RiskBand } from "../../components/RiskSystem";

const CA_REGION = {
  latitude: 36.5,
  longitude: -120.5,
  latitudeDelta: 9.5,
  longitudeDelta: 9.5,
};

export default function MapTab() {
  const [beaches, setBeaches] = useState<ParentBeachSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<ParentBeachSummary | null>(null);
  const router = useRouter();
  const mapRef = useRef<MapView>(null);

  useEffect(() => {
    getParentBeaches()
      .then((items) => setBeaches(filterModeledBeaches(items)))
      .finally(() => setLoading(false));
  }, []);

  const markers = useMemo(
    () =>
      beaches.filter(
        (b) =>
          typeof b.geometry?.latitude === "number" &&
          typeof b.geometry?.longitude === "number"
      ),
    [beaches]
  );

  function onMarkerPress(b: ParentBeachSummary) {
    setSelected(b);
    mapRef.current?.animateToRegion(
      {
        latitude: b.geometry.latitude,
        longitude: b.geometry.longitude,
        latitudeDelta: 0.4,
        longitudeDelta: 0.4,
      },
      400
    );
  }

  const selectedBand = (selected?.risk_band as RiskBand | null) ?? null;

  return (
    <View style={s.root}>
      <MapView
        ref={mapRef}
        provider={PROVIDER_DEFAULT}
        initialRegion={CA_REGION}
        style={StyleSheet.absoluteFillObject}
        onPress={() => setSelected(null)}
      >
        {markers.map((b) => {
          const band = b.risk_band as RiskBand | null;
          const fill = band ? bandColor(band) : palette.muted;
          const isSelected = selected?.id === b.id;
          return (
            <Marker
              key={b.id}
              coordinate={{
                latitude: b.geometry.latitude,
                longitude: b.geometry.longitude,
              }}
              onPress={(e) => {
                e.stopPropagation?.();
                onMarkerPress(b);
              }}
              tracksViewChanges={isSelected}
              anchor={{ x: 0.5, y: 0.5 }}
            >
              <View
                style={[
                  s.marker,
                  {
                    backgroundColor: fill,
                    borderColor: palette.white,
                  },
                  isSelected && s.markerSelected,
                ]}
              />
            </Marker>
          );
        })}
      </MapView>

      {/* Floating header card */}
      <SafeAreaView edges={["top"]} style={s.header} pointerEvents="box-none">
        <View style={s.headerCard}>
          <View>
            <Text style={s.headerEyebrow}>Statewide</Text>
            <Text style={s.headerTitle}>California beaches</Text>
            <Text style={s.headerSub}>
              {markers.length} stations · tap a pin
            </Text>
          </View>
          <View style={s.legend}>
            {(["Low", "Moderate", "High", "Very High"] as RiskBand[]).map(
              (band) => (
                <View key={band} style={s.legendRow}>
                  <View
                    style={[
                      s.legendDot,
                      { backgroundColor: bandColor(band) },
                    ]}
                  />
                  <Text style={s.legendLabel}>{band}</Text>
                </View>
              )
            )}
          </View>
        </View>
      </SafeAreaView>

      {loading && (
        <View style={s.loader}>
          <ActivityIndicator color={palette.navy} size="large" />
        </View>
      )}

      {selected && (
        <View style={s.callout} pointerEvents="box-none">
          <View style={s.calloutCard}>
            <View style={{ flex: 1, marginRight: space.md }}>
              <Text style={s.calloutRegion}>
                {selected.region}  ·  {selected.county} County
              </Text>
              <Text style={s.calloutName} numberOfLines={2}>
                {selected.name}
              </Text>
              {selectedBand ? (
                <View style={s.calloutBandRow}>
                  <DropRow band={selectedBand} size={9} />
                  <Text
                    style={[
                      s.calloutBand,
                      { color: bandColor(selectedBand) },
                    ]}
                  >
                    {selectedBand}
                  </Text>
                </View>
              ) : (
                <Text style={s.calloutNoBand}>Forecast unavailable</Text>
              )}
            </View>
            <TouchableOpacity
              onPress={() => {
                if (selected.station_count > 1) {
                  router.push(`/parent/${selected.id}` as any);
                } else {
                  router.push(`/beach/${selected.member_beach_ids[0]}` as any);
                }
              }}
              style={s.calloutBtn}
              activeOpacity={0.85}
            >
              <Text style={s.calloutBtnText}>Open</Text>
              <Feather
                name="arrow-up-right"
                size={14}
                color={palette.bone}
                style={{ marginLeft: 4 }}
              />
            </TouchableOpacity>
          </View>
        </View>
      )}
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: palette.ecru },

  marker: {
    width: 14,
    height: 14,
    borderRadius: 7,
    borderWidth: 2,
    shadowColor: palette.shadow,
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.25,
    shadowRadius: 3,
    elevation: 3,
  },
  markerSelected: {
    width: 22,
    height: 22,
    borderRadius: 11,
    borderWidth: 3,
  },

  header: {
    position: "absolute",
    top: 0,
    left: 0,
    right: 0,
    padding: space.md,
  },
  headerCard: {
    backgroundColor: "rgba(250,246,238,0.96)",
    borderRadius: radius.lg,
    paddingHorizontal: space.lg,
    paddingVertical: space.md,
    borderWidth: 1,
    borderColor: palette.lineSoft,
    ...shadows.card,
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "flex-start",
    gap: space.md,
  },
  headerEyebrow: { ...typography.eyebrow, color: palette.muted },
  headerTitle: { fontSize: 16, fontWeight: "700", color: palette.navyInk, marginTop: 2 },
  headerSub: { fontSize: 11, color: palette.muted, marginTop: 2 },

  legend: { gap: 4, paddingTop: 2 },
  legendRow: { flexDirection: "row", alignItems: "center", gap: 6 },
  legendDot: { width: 8, height: 8, borderRadius: 4 },
  legendLabel: { fontSize: 9, fontWeight: "600", color: palette.muted },

  loader: {
    position: "absolute",
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    alignItems: "center",
    justifyContent: "center",
  },

  callout: {
    position: "absolute",
    left: space.md,
    right: space.md,
    bottom: space.lg,
  },
  calloutCard: {
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: palette.bone,
    borderRadius: radius.xl,
    paddingHorizontal: space.lg,
    paddingVertical: space.md,
    borderWidth: 1,
    borderColor: palette.lineSoft,
    ...shadows.hero,
  },
  calloutRegion: {
    ...typography.eyebrow,
    color: palette.muted,
    fontSize: 9,
  },
  calloutName: {
    fontSize: 16,
    fontWeight: "700",
    color: palette.navyInk,
    marginTop: 3,
    lineHeight: 20,
  },
  calloutBandRow: {
    flexDirection: "row",
    alignItems: "center",
    marginTop: 6,
    gap: 6,
  },
  calloutBand: {
    fontSize: 11,
    fontWeight: "700",
    letterSpacing: 0.4,
    textTransform: "uppercase",
  },
  calloutNoBand: { fontSize: 11, color: palette.muted, marginTop: 6 },

  calloutBtn: {
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: palette.navy,
    paddingHorizontal: space.lg,
    paddingVertical: 11,
    borderRadius: radius.md,
  },
  calloutBtnText: {
    color: palette.bone,
    fontSize: 13,
    fontWeight: "700",
    letterSpacing: 0.2,
  },
});
