"use client";
import { useEffect, useState } from "react";
import { getBeaches, type BeachSummary } from "@/lib/api";
import { filterModeledBeaches } from "@/lib/coverage";
import LocationScreen from "./LocationScreen";

export default function MobileHome() {
  const [beaches, setBeaches] = useState<BeachSummary[]>([]);
  useEffect(() => { getBeaches().then((items) => setBeaches(filterModeledBeaches(items))); }, []);
  return <LocationScreen beaches={beaches} />;
}
