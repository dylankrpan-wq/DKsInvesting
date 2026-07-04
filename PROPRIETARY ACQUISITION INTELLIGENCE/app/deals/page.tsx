import { PageHeader } from "@/components/PageHeader";
import { DealExplorer } from "@/components/DealExplorer";
import { allRows } from "@/lib/analytics";

export default function DealsPage() {
  const rows = allRows();
  return (
    <>
      <PageHeader title="Deal Explorer" subtitle="Filter, search and rank the tracked acquisition universe" />
      <DealExplorer rows={rows} />
    </>
  );
}
