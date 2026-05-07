"use client";
import { View, Text } from "react-native";

export type RiskBand = "Low" | "Moderate" | "High" | "Very High";

export const RISK_ORDER: RiskBand[] = ["Low", "Moderate", "High", "Very High"];

export const RISK_COPY: Record<RiskBand, { head: string; sub: string; cfu: string; drops: number }> = {
  Low:         { head: "Below standard.", sub: "Lower modeled exceedance risk today.",        cfu: "< 35 CFU",  drops: 1 },
  Moderate:    { head: "Caution.",         sub: "Elevated modeled risk today.",                 cfu: "35–104",    drops: 2 },
  High:        { head: "Warning.",         sub: "Avoid water contact and check advisories.",    cfu: "104–320",   drops: 3 },
  "Very High": { head: "Closure level.",   sub: "Check posted county advisory before entering or high model prediction.", cfu: "> 320",     drops: 3 },
};

export const RISK_COLORS_DEEP: Record<RiskBand, { fill: string; bg: string; ink: string }> = {
  Low:         { fill: "#2b9e79", bg: "#d8efe4", ink: "#175d43" },
  Moderate:    { fill: "#c99b2d", bg: "#f3e6c1", ink: "#6d4a05" },
  High:        { fill: "#c7552e", bg: "#f2d9ca", ink: "#7a2d15" },
  "Very High": { fill: "#8a2a20", bg: "#ecc9c1", ink: "#561611" },
};

// Drop glyph — teardrop shape, filled/empty per severity
function Drop({ filled, color, size = 13, exclaim = false }: {
  filled: boolean; color: string; size?: number; exclaim?: boolean;
}) {
  const r = size / 2;
  return (
    <View style={{
      width: size, height: size * 1.25,
      borderTopLeftRadius: r, borderTopRightRadius: r,
      borderBottomLeftRadius: r * 0.45, borderBottomRightRadius: r * 0.45,
      backgroundColor: filled ? color : "transparent",
      borderWidth: 1.2, borderColor: filled ? color : color + "55",
      alignItems: "center", justifyContent: "center",
    }}>
      {exclaim && (
        <Text style={{ fontSize: size * 0.55, fontWeight: "800", color: "#fff", lineHeight: size * 0.6 }}>!</Text>
      )}
    </View>
  );
}

// 1-3 drops showing severity
export function DropRow({ band, size = 13 }: { band: RiskBand; size?: number }) {
  const { drops, fill, ink } = { ...RISK_COPY[band], ...RISK_COLORS_DEEP[band] };
  const vh = band === "Very High";
  return (
    <View style={{ flexDirection: "row", gap: 3, alignItems: "flex-end" }}>
      {[0, 1, 2].map((i) => (
        <Drop
          key={i}
          filled={i < drops}
          color={fill}
          size={size}
          exclaim={vh && i === 2}
        />
      ))}
    </View>
  );
}

// 4-slot bar filling left to right per severity
export function SeverityBar({ band, height = 6 }: { band: RiskBand; height?: number }) {
  const idx = RISK_ORDER.indexOf(band);
  return (
    <View style={{ flexDirection: "row", gap: 3 }}>
      {RISK_ORDER.map((b, i) => {
        const on = i <= idx;
        return (
          <View
            key={b}
            style={{
              flex: 1, height,
              borderRadius: height / 2,
              backgroundColor: on ? RISK_COLORS_DEEP[b].fill : "#e2e8f0",
              opacity: on ? (i === idx ? 1 : 0.45) : 1,
            }}
          />
        );
      })}
    </View>
  );
}

// Compact risk pill with drop + label
export function RiskPill({ band }: { band: RiskBand }) {
  const { fill, bg, ink } = RISK_COLORS_DEEP[band];
  return (
    <View style={{ flexDirection: "row", alignItems: "center", gap: 6, backgroundColor: bg, paddingHorizontal: 10, paddingVertical: 5, borderRadius: 999 }}>
      <DropRow band={band} size={10} />
      <Text style={{ fontSize: 11, fontWeight: "700", color: ink, letterSpacing: 0.3 }}>{band}</Text>
    </View>
  );
}
