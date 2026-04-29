import { useEffect, useState } from "react";
import { View, Text, TextInput, TouchableOpacity, SectionList, StyleSheet, ActivityIndicator } from "react-native";
import { useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { getParentBeaches, type ParentBeachSummary } from "../../lib/api";

const REGIONS = ["All", "SoCal", "Central", "NorCal"];
const REGION_LABELS: Record<string, string> = {
  SoCal: "Southern California",
  Central: "Central California",
  NorCal: "Northern California",
};

export default function SearchTab() {
  const [beaches, setBeaches] = useState<ParentBeachSummary[]>([]);
  const [q, setQ] = useState("");
  const [region, setRegion] = useState("All");
  const [loading, setLoading] = useState(true);
  const router = useRouter();

  useEffect(() => {
    getParentBeaches().then(setBeaches).finally(() => setLoading(false));
  }, []);

  const filtered = beaches
    .filter((b) => region === "All" || b.region === REGION_LABELS[region] || b.region === region)
    .filter((b) =>
      !q ||
      b.name.toLowerCase().includes(q.toLowerCase()) ||
      b.county.toLowerCase().includes(q.toLowerCase())
    );

  const grouped: Record<string, ParentBeachSummary[]> = {};
  filtered.forEach((b) => { (grouped[b.region] = grouped[b.region] ?? []).push(b); });
  const sections = Object.entries(grouped).map(([r, data]) => ({
    title: REGION_LABELS[r] ?? r,
    count: data.length,
    data,
  }));

  return (
    <SafeAreaView style={s.root} edges={["top"]}>
      {/* Header */}
      <View style={s.header}>
        <Text style={s.title}>Browse beaches</Text>
        <View style={s.searchBox}>
          <Text>🔍</Text>
          <TextInput
            style={s.searchInput}
            value={q}
            onChangeText={setQ}
            placeholder={`Search ${beaches.length}+ beaches`}
            placeholderTextColor="#94a3b8"
            clearButtonMode="while-editing"
          />
        </View>
        {/* Region pills */}
        <View style={s.pills}>
          {REGIONS.map((r) => (
            <TouchableOpacity key={r} onPress={() => setRegion(r)}
              style={[s.pill, region === r && s.pillActive]}>
              <Text style={[s.pillText, region === r && s.pillTextActive]}>{r}</Text>
            </TouchableOpacity>
          ))}
        </View>
      </View>

      {loading ? (
        <ActivityIndicator style={{ marginTop: 32 }} color="#0b4266" />
      ) : (
        <SectionList
          sections={sections}
          keyExtractor={(b) => b.id}
          contentContainerStyle={{ paddingBottom: 100 }}
          renderSectionHeader={({ section }) => (
            <View style={s.sectionHeader}>
              <Text style={s.sectionLabel}>{section.title}</Text>
              <Text style={s.sectionCount}>{section.count}</Text>
            </View>
          )}
          renderItem={({ item: b }) => (
            <TouchableOpacity
              onPress={() => router.push(`/beach/${b.id}` as any)}
              style={s.row}>
              <View style={s.dot} />
              <View style={{ flex: 1 }}>
                <Text style={s.name}>{b.name}</Text>
                <Text style={s.sub}>{b.county} County</Text>
              </View>
              <Text style={s.chevron}>›</Text>
            </TouchableOpacity>
          )}
          ListEmptyComponent={
            <View style={{ padding: 40, alignItems: "center" }}>
              <Text style={{ fontSize: 15, fontWeight: "600", color: "#64748b" }}>No beaches match</Text>
              <Text style={{ fontSize: 13, color: "#94a3b8", marginTop: 4 }}>Try a different search.</Text>
            </View>
          }
          stickySectionHeadersEnabled={false}
        />
      )}
    </SafeAreaView>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: "#f2f4f7" },
  header: { backgroundColor: "#fff", padding: 20, paddingBottom: 0, borderBottomWidth: 1, borderBottomColor: "#e5e7eb" },
  title: { fontSize: 24, fontWeight: "700", color: "#0f172a", marginBottom: 12 },
  searchBox: {
    flexDirection: "row", alignItems: "center", gap: 10,
    backgroundColor: "#f1f5f9", borderRadius: 14, paddingHorizontal: 14, paddingVertical: 12,
  },
  searchInput: { flex: 1, fontSize: 15, color: "#0f172a" },
  pills: { flexDirection: "row", gap: 6, paddingVertical: 12 },
  pill: { paddingHorizontal: 14, paddingVertical: 6, borderRadius: 999, borderWidth: 1, borderColor: "#e5e7eb", backgroundColor: "#fff" },
  pillActive: { backgroundColor: "#0b4266", borderColor: "#0b4266" },
  pillText: { fontSize: 12, fontWeight: "600", color: "#0f172a" },
  pillTextActive: { color: "#fff" },
  sectionHeader: { flexDirection: "row", justifyContent: "space-between", paddingHorizontal: 20, paddingTop: 20, paddingBottom: 8 },
  sectionLabel: { fontSize: 11, fontWeight: "700", color: "#64748b", textTransform: "uppercase", letterSpacing: 1 },
  sectionCount: { fontSize: 11, color: "#94a3b8" },
  row: {
    flexDirection: "row", alignItems: "center", gap: 12,
    marginHorizontal: 20, marginBottom: 8, padding: 12,
    backgroundColor: "#fff", borderWidth: 1, borderColor: "#e5e7eb", borderRadius: 14,
  },
  dot: { width: 8, height: 8, borderRadius: 4, backgroundColor: "#94a3b8" },
  name: { fontSize: 14, fontWeight: "600", color: "#0f172a" },
  sub: { fontSize: 11, color: "#64748b", marginTop: 2 },
  chevron: { fontSize: 20, color: "#cbd5e1" },
});
