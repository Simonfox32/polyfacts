import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Polyfacts — Political Fact-Check Overlay",
  description: "Evidence-backed fact-checking for political broadcasts",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-background antialiased">{children}</body>
    </html>
  );
}
