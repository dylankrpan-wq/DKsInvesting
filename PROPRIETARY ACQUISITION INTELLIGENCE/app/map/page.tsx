import { PageHeader } from "@/components/PageHeader";
import { DealMap } from "@/components/DealMap";
import { allRows } from "@/lib/analytics";

export default function MapPage() {
  const rows = allRows();
  return (
    <>
      <PageHeader title="Deal Map" subtitle="Every tracked business geolocated · color = opportunity score · size = asking price" />
      <DealMap rows={rows} />
    </>
  );
}
