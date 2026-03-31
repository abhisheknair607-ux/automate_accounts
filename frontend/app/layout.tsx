import "./globals.css";

import type { ReactNode } from "react";


export const metadata = {
  title: "Invoice Reconciliation MVP",
  description: "Large-retailer invoice and delivery docket reconciliation review console."
};


export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className="site-shell">
          <div className="site-chrome">
            <span className="eyebrow">Retail Finance Operations</span>
            <h1>Invoice Reconciliation Platform</h1>
            <p>OCR extraction, reconciliation rules, exception handling, and accounting export in one MVP workspace.</p>
          </div>
          <main>{children}</main>
        </div>
      </body>
    </html>
  );
}
