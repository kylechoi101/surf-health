import { Tabs } from "expo-router";
import { View, Text, Platform } from "react-native";
import { Feather } from "@expo/vector-icons";
import { palette } from "../../lib/theme";

function TabIcon({
  focused,
  iconName,
  label,
}: {
  focused: boolean;
  iconName: keyof typeof Feather.glyphMap;
  label: string;
}) {
  const tint = focused ? palette.navyInk : palette.muted;
  return (
    <View style={{ alignItems: "center", justifyContent: "center", gap: 3, minWidth: 56, paddingTop: 6 }}>
      <Feather name={iconName} size={20} color={tint} />
      <Text
        style={{
          fontSize: 10,
          fontWeight: focused ? "700" : "600",
          color: tint,
          letterSpacing: 0.2,
        }}
      >
        {label}
      </Text>
    </View>
  );
}

export default function TabLayout() {
  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarShowLabel: false,
        tabBarStyle: {
          backgroundColor: "rgba(250,246,238,0.96)",
          borderTopColor: palette.lineSoft,
          borderTopWidth: 1,
          height: Platform.OS === "ios" ? 84 : 70,
          paddingTop: 4,
          paddingBottom: Platform.OS === "ios" ? 24 : 10,
        },
        tabBarItemStyle: {
          paddingTop: 0,
        },
      }}
    >
      <Tabs.Screen
        name="index"
        options={{
          tabBarIcon: ({ focused }) => (
            <TabIcon focused={focused} iconName="home" label="Today" />
          ),
        }}
      />
      <Tabs.Screen
        name="map"
        options={{
          tabBarIcon: ({ focused }) => (
            <TabIcon focused={focused} iconName="map" label="Map" />
          ),
        }}
      />
      <Tabs.Screen
        name="search"
        options={{
          tabBarIcon: ({ focused }) => (
            <TabIcon focused={focused} iconName="search" label="Browse" />
          ),
        }}
      />
    </Tabs>
  );
}
