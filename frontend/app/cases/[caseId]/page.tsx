"use client";

import { useParams } from "next/navigation";

import { CaseOverview } from "@/components/case-overview";


export default function CasePage() {
  const { caseId } = useParams<{ caseId: string }>();
  return <CaseOverview caseId={caseId} />;
}
