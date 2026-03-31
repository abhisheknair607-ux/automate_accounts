import { CaseSectionView } from "@/components/case-section-view";


export default function ExceptionsPage({ params }: { params: { caseId: string } }) {
  return <CaseSectionView caseId={params.caseId} section="exceptions" />;
}
