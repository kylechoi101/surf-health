import { useEffect, useMemo, useRef, useState } from "react";
import { View, Text, TouchableOpacity, StyleSheet, ActivityIndicator, Platform } from "react-native";
import { useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import MapView, { Marker, PROVIDER_DEFAULT } from "react-native-maps";
import { getBeaches, type BeachSummary } from "../../lib/api";
import { filterModeledBeaches } from "../../lib/coverage";

const CA_REGION = {
  latitude: 36.5,
  longitude: -120.5,
  latitudeDelta: 9.5,
  longitudeDelta: 9.5,
};

export default function MapTab() {
  const [beaches, setBeaches] = useState<BeachSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<BeachSummary | null>(null);
  const router = useRouter();
  const mapRef = useRef<MapView>(null);

  useEffect(() => {
    getBeaches().then((items) => setBeaches(filterModeledBeaches(items))).finally(() => setLoading(false));
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

  function onMarkerPress(b: BeachSummary) {
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

  return (
    <View style={s.root}>
      <MapView
        ref={mapRef}
        provider={PROVIDER_DEFAULT}
        initialRegion={CA_REGION}
        style={StyleSheet.absoluteFillObject}
        onPress={() => setSelected(null)}
      >
        {markers.map((b) => (
          <Marker
            key={b.id}
            coordinate={{
              latitude: b.geometry.latitude,
              longitude: b.geometry.longitude,
            }}
            pinColor="#0b4266"
            onPress={(e) => {
              e.stopPropagation?.();
              onMarkerPress(b);
            }}
            tracksViewChanges={false}
          />
        ))}
      </MapView>

      <SafeAreaView edges={["top"]} style={s.header} pointerEvents="box-none">
        <View style={s.headerCard}>
          <Text style={s.headerTitle}>California beaches</Text>
          <Text style={s.headerSub}>{markers.length} stations · tap a pin</Text>
        </View>
      </SafeAreaView>

      {loading && (
        <View style={s.loader}>
          <ActivityIndicator color="#0b4266" size="large" />
        </View>
      )}

      {selected && (
        <View style={s.callout} pointerEvents="box-none">
          <View style={s.calloutCard}>
            <View style={{ flex: 1 }}>
              <Text style={s.calloutRegion}>{selected.region}</Text>
              <Text style={s.calloutName}>{selected.name}</Text>
              <Text style={s.calloutSub}>
                {selected.county} County
              </Text>
            </View>
            <TouchableOpacity
              onPress={() => router.push(`/beach/${selected.id}` as any)}
              style={s.calloutBtn}
            >
              <Text style={s.calloutBtnText}>Open</Text>
            </TouchableOpacity>
          </View>
        </View>
      )}
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: "#e2e8f0" },
  header: {
    position: "absolute",
    top: 0,
    left: 0,
    right: 0,
    padding: 14,
  },
  headerCard: {
    backgroundColor: "rgba(255,255,255,0.95)",
    borderRadius: 14,
    paddingHorizontal: 16,
    paddingVertical: 12,
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 6 },
    shadowOpacity: 0.12,
    shadowRadius: 14,
    elevation: 4,
  },
  headerTitle: { fontSize: 15, fontWeight: "700", color: "#0f172a" },
  headerSub: { fontSize: 11, color: "#64748b", marginTop: 2 },
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
    left: 12,
    right: 12,
    bottom: 14,
  },
  calloutCard: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    backgroundColor: "#fff",
    borderRadius: 18,
    padding: 14,
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.18,
    shadowRadius: 18,
    elevation: 6,
  },
  calloutRegion: {
    fontSize: 10,
    fontWeight: "700",
    color: "#64748b",
    textTransform: "uppercase",
    letterSpacing: 1,
  },
  calloutName: { fontSize: 16, fontWeight: "700", color: "#0f172a", marginTop: 2 },
  calloutSub: { fontSize: 12, color: "#64748b", marginTop: 3 },
  calloutBtn: {
    backgroundColor: "#0b4266",
    paddingHorizontal: 16,
    paddingVertical: 10,
    borderRadius: 12,
  },
  calloutBtnText: { color: "#fff", fontSize: 13, fontWeight: "700" },
});
