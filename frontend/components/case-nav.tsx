"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const sections = [
  { href: "", label: "Overview" },
  { href: "/invoice", label: "Invoice" },
  { href: "/docket", label: "Docket" },
  { href: "/reconciliation", label: "Reconciliation" },
  { href: "/exports", label: "Exports" }
];

export function CaseNav({ caseId }: { caseId: string }) {
  const pathname = usePathname();

  return (
    <nav className="case-nav">
      {sections.map((section) => {
        const href = `/cases/${caseId}${section.href}`;
        const isActive = pathname === href;
        return (
          <Link key={href} className={`nav-link ${isActive ? "is-active" : ""}`} href={href}>
            {section.label}
          </Link>
        );
      })}
    </nav>
  );
}
