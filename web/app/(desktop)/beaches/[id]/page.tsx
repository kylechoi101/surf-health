import { listBeaches } from "@/lib/curated";
import { filterModeledBeaches } from "@/lib/coverage";
import BeachDetail from "./BeachDetail";

export async function generateStaticParams() {
  return filterModeledBeaches(listBeaches()).map((beach) => ({
    id: beach.id,
  }));
}

export default async function Page(props: { params: Promise<{ id: string }> }) {
  await props.params;
  return <BeachDetail />;
}
