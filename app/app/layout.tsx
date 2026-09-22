import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Visual Inspection",
  description: "Native multimodal manufacturing data with Databricks FILE",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
