import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Visual Quality Inspection",
  description: "Automated visual quality inspection for pharmaceutical manufacturing",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
