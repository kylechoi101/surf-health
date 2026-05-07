import { useEffect, useState } from "react";
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  SectionList,
  StyleSheet,
  ActivityIndicator,
} from "react-native";
import { useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { getParentBeaches, type ParentBeachSummary } from "../../lib/api";
import { filterModeledBeaches } from "../../lib/coverage";
import { palette, radius, shadows, space, typography, bandColor } from "../../lib/theme";
import { DropRow, type RiskBand } from "../../components/RiskSystem";

const REGIONS = ["All", "SoCal", "Central", "NorCal"] as const;
const REGION_LABELS: Record<string, string> = {
  SoCal: "Southern California",
  Central: "Central California",
  NorCal: "Northern California",
};

export default function SearchTab() {
  const [beaches, setBeaches] = useState<ParentBeachSummary[]>([]);
  const [q, setQ] = useState("");
  const [region, setRegion] = useState<(typeof REGIONS)[number]>("All");
  const [loading, setLoading] = useState(true);
  const router = useRouter();

  useEffect(() => {
    getParentBeaches()
      .then((items) => setBeaches(filterModeledBeaches(items)))
      .finally(() => setLoading(false));
  }, []);

  function pick(b: ParentBeachSummary) {
    if (b.station_count > 1) {
      router.push(`/parent/${b.id}` as any);
    } else {
      router.push(`/beach/${b.member_beach_ids[0]}` as any);
    }
  }

  const filtered = beaches
    .filter((b) => region === "All" || b.region === REGION_LABELS[region] || b.region === region)
    .filter(
      (b) =>
        !q ||
        b.name.toLowerCase().includes(q.toLowerCase()) ||
        b.county.toLowerCase().includes(q.toLowerCase())
    );

  const grouped: Record<string, ParentBeachSummary[]> = {};
  filtered.forEach((b) => {
    (grouped[b.region] = grouped[b.region] ?? []).push(b);
  });
  const sections = Object.entries(grouped).map(([r, data]) => ({
    title: REGION_LABELS[r] ?? r,
    count: data.length,
    data,
  }));

  return (
    <SafeAreaView style={s.root} edges={["top"]}>
      <View style={s.header}>
        <Text style={s.eyebrow}>Browse</Text>
        <Text style={s.title}>California beaches</Text>

        <View style={s.searchBox}>
          <Feather name="search" size={16} color={palette.muted} />
          <TextInput
            style={s.searchInput}
            value={q}
            onChangeText={setQ}
            placeholder={`Search ${beaches.length} beaches`}
            placeholderTextColor={palette.muted}
            clearButtonMode="while-editing"
          />
        </View>

        <View style={s.pills}>
          {REGIONS.map((r) => {
            const active = region === r;
            return (
              <TouchableOpacity
                key={r}
                onPress={() => setRegion(r)}
                style={[s.pill, active && s.pillActive]}
                activeOpacity={0.7}
              >
                <Text style={[s.pillText, active && s.pillTextActive]}>{r}</Text>
              </TouchableOpacity>
            );
          })}
        </View>
      </View>

      {loading ? (
        <View style={s.loaderWrap}>
          <ActivityIndicator color={palette.navy} />
        </View>
      ) : (
        <SectionList
          sections={sections}
          keyExtractor={(b) => b.id}
          contentContainerStyle={{ paddingBottom: 120, paddingTop: space.sm }}
          renderSectionHeader={({ section }) => (
            <View style={s.sectionHeader}>
              <Text style={s.sectionLabel}>{section.title}</Text>
              <Text style={s.sectionCount}>{section.count}</Text>
            </View>
          )}
          renderItem={({ item: b }) => {
            const band = b.risk_band as RiskBand | null;
            return (
              <TouchableOpacity
                onPress={() => pick(b)}
                style={s.row}
                activeOpacity={0.65}
              >
                {band ? (
                  <DropRow band={band} size={11} />
                ) : (
                  <View style={s.dotInactive} />
                )}
                <View style={{ flex: 1 }}>
                  <View style={s.nameRow}>
                    <Text style={s.name} numberOfLines={1}>
                      {b.name}
                    </Text>
                    {b.has_active_advisory && (
                      <Feather
                        name="alert-triangle"
                        size={12}
                        color="#b91c1c"
                        style={{ marginLeft: 6 }}
                      />
                    )}
                  </View>
                  <Text style={s.sub}>
                    {b.county} County
                    {b.station_count > 1 ? `  ·  ${b.station_count} stations` : ""}
                  </Text>
                </View>
                {band && (
                  <Text style={[s.bandLabel, { color: bandColor(band) }]}>
                    {band}
                  </Text>
                )}
                <Feather name="chevron-right" size={18} color={palette.sand} />
              </TouchableOpacity>
            );
          }}
          ListEmptyComponent={
            <View style={s.emptyWrap}>
              <Text style={s.emptyTitle}>No beaches match.</Text>
              <Text style={s.emptySub}>Try a different search or region.</Text>
            </View>
          }
          stickySectionHeadersEnabled={false}
        />
      )}
    </SafeAreaView>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: palette.bone },

  header: {
    backgroundColor: palette.bone,
    paddingHorizontal: space.xl,
    paddingTop: space.sm,
    paddingBottom: space.lg,
    borderBottomWidth: 1,
    borderBottomColor: palette.lineSoft,
  },
  eyebrow: { ...typography.eyebrow, color: palette.muted },
  title: { ...typography.title, color: palette.navyInk, marginTop: 4 },

  searchBox: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    backgroundColor: palette.ecruDeep,
    borderRadius: radius.md,
    paddingHorizontal: space.md,
    paddingVertical: 11,
    marginTop: space.lg,
  },
  searchInput: { flex: 1, fontSize: 15, color: palette.ink },

  pills: { flexDirection: "row", gap: 6, paddingTop: space.md, flexWrap: "wrap" },
  pill: {
    paddingHorizontal: 14,
    paddingVertical: 6,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: palette.line,
    backgroundColor: palette.bone,
  },
  pillActive: { backgroundColor: palette.navy, borderColor: palette.navy },
  pillText: { fontSize: 12, fontWeight: "600", color: palette.ink },
  pillTextActive: { color: palette.bone },

  loaderWrap: { padding: 32, alignItems: "center" },

  sectionHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    paddingHorizontal: space.xl,
    paddingTop: space.lg,
    paddingBottom: space.sm,
  },
  sectionLabel: { ...typography.eyebrow, color: palette.muted },
  sectionCount: { fontSize: 11, color: palette.muted, fontWeight: "600" },

  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: space.md,
    marginHorizontal: space.xl,
    marginBottom: 8,
    padding: space.md,
    backgroundColor: palette.white,
    borderWidth: 1,
    borderColor: palette.lineSoft,
    borderRadius: radius.md,
    ...shadows.card,
    shadowOpacity: 0.04,
  },
  dotInactive: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: palette.sand,
  },
  nameRow: { flexDirection: "row", alignItems: "center" },
  name: { fontSize: 14, fontWeight: "600", color: palette.ink, flexShrink: 1 },
  sub: { fontSize: 12, color: palette.muted, marginTop: 2 },
  bandLabel: {
    fontSize: 10,
    fontWeight: "700",
    letterSpacing: 0.4,
    textTransform: "uppercase",
  },

  emptyWrap: { padding: 40, alignItems: "center" },
  emptyTitle: { fontSize: 15, fontWeight: "600", color: palette.ink },
  emptySub: { fontSize: 13, color: palette.muted, marginTop: 4 },
});
