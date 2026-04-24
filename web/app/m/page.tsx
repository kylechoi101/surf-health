import Link from "next/link";
import { getBeaches } from "@/lib/api";
import LocationScreen from "./LocationScreen";

export default async function MobileHome() {
  const beaches = await getBeaches();
  return <LocationScreen beaches={beaches} />;
}
