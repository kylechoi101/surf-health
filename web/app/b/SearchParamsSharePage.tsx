"use client";

import { useSearchParams } from "next/navigation";

import BeachSharePage from "./[id]/BeachSharePage";

export default function SearchParamsSharePage() {
  const searchParams = useSearchParams();
  const beachId = searchParams.get("id") ?? undefined;

  return <BeachSharePage beachId={beachId} />;
}
