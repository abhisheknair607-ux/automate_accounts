"use client";

import { useParams } from "next/navigation";

import { CaseSectionView } from "@/components/case-section-view";


export default function DocketPage() {
  const { caseId } = useParams<{ caseId: string }>();
  return <CaseSectionView caseId={caseId} section="docket" />;
}
