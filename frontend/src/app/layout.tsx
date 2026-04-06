import type { Metadata } from "next";
import { NavBar } from "@/components/NavBar";
import { AuthProvider } from "@/context/AuthContext";
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
      <body className="min-h-screen bg-background pt-14 text-foreground antialiased">
        <AuthProvider>
          <NavBar />
          {children}
        </AuthProvider>
      </body>
    </html>
  );
}
