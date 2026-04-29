"use client";
import { useEffect, useState } from "react";
import { getBeaches, type BeachSummary } from "@/lib/api";
import LocationScreen from "./LocationScreen";

export default function MobileHome() {
  const [beaches, setBeaches] = useState<BeachSummary[]>([]);
  useEffect(() => { getBeaches().then(setBeaches); }, []);
  return <LocationScreen beaches={beaches} />;
}
