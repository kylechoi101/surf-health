import { Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";

export default function RootLayout() {
  return (
    <>
      <StatusBar style="light" />
      <Stack screenOptions={{ headerShown: false }}>
        <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
        <Stack.Screen name="beach/[id]" options={{ headerShown: false, animation: "slide_from_right" }} />
        <Stack.Screen name="beach/[id]/detail" options={{ headerShown: false, animation: "slide_from_right" }} />
      </Stack>
    </>
  );
}
