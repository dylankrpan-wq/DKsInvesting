import { PageHeader } from "@/components/PageHeader";
import { SbaCalculator } from "@/components/SbaCalculator";

export default function SbaCalculatorPage() {
  const initial = {
    purchasePrice: 1_450_000,
    downPaymentPct: 10,
    sellerNotePct: 10,
    interestRatePct: 11,
    termYears: 10,
    sde: 520_000,
    newOwnerSalary: 85_000,
  };
  return (
    <>
      <PageHeader title="SBA Acquisition Calculator" subtitle="Model financing, DSCR, cash-on-cash and maximum supportable price" />
      <div className="p-6">
        <SbaCalculator initial={initial} />
      </div>
    </>
  );
}
