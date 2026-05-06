import { Tabs } from "expo-router";
import { View, Text } from "react-native";
import { Feather } from "@expo/vector-icons";

function TabIcon({ focused, iconName, label }: { focused: boolean; iconName: keyof typeof Feather.glyphMap; label: string }) {
  return (
    <View style={{ alignItems: "center", gap: 2, flexShrink: 0, minWidth: 46 }}>
      <Feather name={iconName} size={20} color={focused ? "#0b4266" : "#94a3b8"} />
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
          tabBarIcon: ({ focused }) => <TabIcon focused={focused} iconName="home" label="Today" />,
        }}
      />
      <Tabs.Screen
        name="map"
        options={{
          tabBarIcon: ({ focused }) => <TabIcon focused={focused} iconName="map" label="Map" />,
        }}
      />
      <Tabs.Screen
        name="search"
        options={{
          tabBarIcon: ({ focused }) => <TabIcon focused={focused} iconName="search" label="Search" />,
        }}
      />
    </Tabs>
  );
}
