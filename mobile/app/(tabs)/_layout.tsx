import { Tabs } from "expo-router";
import { View, Text } from "react-native";

function TabIcon({ focused, emoji, label }: { focused: boolean; emoji: string; label: string }) {
  return (
    <View style={{ alignItems: "center", gap: 2, flexShrink: 0, minWidth: 46 }}>
      <Text style={{ fontSize: 20 }}>{emoji}</Text>
      <Text style={{ fontSize: 9, fontWeight: "600", color: focused ? "#0b4266" : "#94a3b8" }}>{label}</Text>
    </View>
  );
}

export default function TabLayout() {
  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarStyle: {
          backgroundColor: "rgba(255,255,255,0.95)",
          borderTopColor: "#e5e7eb",
          height: 80,
          paddingBottom: 16,
        },
        tabBarShowLabel: false,
      }}
    >
      <Tabs.Screen
        name="index"
        options={{
          tabBarIcon: ({ focused }) => <TabIcon focused={focused} emoji="🏖" label="Today" />,
        }}
      />
      <Tabs.Screen
        name="map"
        options={{
          tabBarIcon: ({ focused }) => <TabIcon focused={focused} emoji="🗺️" label="Map" />,
        }}
      />
      <Tabs.Screen
        name="search"
        options={{
          tabBarIcon: ({ focused }) => <TabIcon focused={focused} emoji="🔍" label="Search" />,
        }}
      />
    </Tabs>
  );
}
