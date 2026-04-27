import { getBeaches } from "@/lib/api";
import BeachDetail from "./BeachDetail";

export async function generateStaticParams() {
  const beaches = await getBeaches({ cache: 'force-cache' });
  return beaches.map((b) => ({
    id: b.id,
  }));
}

export default function Page() {
  return <BeachDetail />;
}
