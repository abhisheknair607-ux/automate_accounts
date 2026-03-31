import { CaseSectionView } from "@/components/case-section-view";


export default function InvoicePage({ params }: { params: { caseId: string } }) {
  return <CaseSectionView caseId={params.caseId} section="invoice" />;
}
