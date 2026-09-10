import type { Metadata } from "next";
import type React from "react";
import { Inter, JetBrains_Mono } from "next/font/google";
import "./globals.css";

// Two typefaces, two jobs.
//
// Inter carries everything a person reads as language — headings, labels,
// prose, buttons. It has the weight range and the tight optical tracking a
// product UI needs, where a grotesque tuned for code does not.
//
// JetBrains Mono carries only what a person reads as a measurement: a frame
// id, a rate, a coordinate. Its figures are unmistakably digits at 11px on a
// projector, and tabular widths mean a number does not jitter between samples.
const ui = Inter({
  variable: "--font-ui",
  subsets: ["latin"],
  display: "swap",
});

const tech = JetBrains_Mono({
  variable: "--font-tech",
  subsets: ["latin"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "NEXA — Adaptive LiDAR perception for dynamic environments",
  description:
    "A ring-sector polar grid running 5 cm cells inside 10 m and 50 cm at 100 m — " +
    "705,771 cells against 16,000,000 for a uniform grid over the same footprint — " +
    "preserving the curbs, potholes and overhangs a 2D occupancy grid destroys.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      className={`${ui.variable} ${tech.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
