import { View, Text, StyleSheet } from "react-native";
import { palette } from "../lib/theme";

export function BetaNotice({ isBeta }: { isBeta?: boolean }) {
  if (!isBeta) return null;
  return (
    <View style={s.container}>
      <Text style={s.label}>Beta forecast</Text>
    </View>
  );
}

export function RecencyBadge({
  sampleAgeDays,
  recencyBand,
}: {
  sampleAgeDays?: number | null;
  recencyBand?: string;
}) {
  if (sampleAgeDays == null && !recencyBand) return null;
  const isStale = recencyBand === "stale" || recencyBand === "very_stale";
  const label =
    sampleAgeDays != null
      ? sampleAgeDays === 0
        ? "Sampled today"
        : sampleAgeDays === 1
          ? "Sampled yesterday"
          : `Sampled ${sampleAgeDays}d ago`
      : recencyBand
        ? `Sample: ${recencyBand.replace("_", " ")}`
        : null;
  if (!label) return null;
  return (
    <View style={[s.container, isStale ? s.stale : s.fresh]}>
      <Text style={[s.label, isStale ? s.staleText : s.freshText]}>{label}</Text>
    </View>
  );
}

const s = StyleSheet.create({
  container: {
    backgroundColor: "#eff6ff",
    borderWidth: 1,
    borderColor: "rgba(147,197,253,0.5)",
    borderRadius: 999,
    paddingHorizontal: 10,
    paddingVertical: 4,
    alignSelf: "flex-start",
  },
  label: {
    fontSize: 10,
    fontWeight: "700",
    color: "#1d4ed8",
    letterSpacing: 0.3,
  },
  stale: { backgroundColor: "#fffbeb", borderColor: "rgba(251,191,36,0.5)" },
  staleText: { color: "#b45309" },
  fresh: { backgroundColor: "#f0fdf4", borderColor: "rgba(134,239,172,0.5)" },
  freshText: { color: palette.muted },
});
