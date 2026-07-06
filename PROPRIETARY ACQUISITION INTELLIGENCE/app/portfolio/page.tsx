import { PageHeader } from "@/components/PageHeader";
import { PortfolioSimulator } from "@/components/PortfolioSimulator";
import { allRows } from "@/lib/analytics";

export default function PortfolioPage() {
  const rows = allRows();
  return (
    <>
      <PageHeader title="Portfolio & What-If Simulator" subtitle="Model multiple acquisitions together — combined IRR, NPV, cash flow and scenarios" />
      <PortfolioSimulator rows={rows} />
    </>
  );
}
