import type { Metadata } from "next";
import "./globals.css";
import { Sidebar } from "@/components/Sidebar";

export const metadata: Metadata = {
  title: "Acquisition Intelligence",
  description: "Source, score, value and monitor businesses for sale — institutional-grade deal intelligence.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className="flex">
          <Sidebar />
          <main className="h-screen flex-1 overflow-y-auto">{children}</main>
        </div>
      </body>
    </html>
  );
}
