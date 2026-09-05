import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "AVR-25D — Adaptive Variable-Resolution 2.5D LiDAR Mapping",
  description:
    "SIH26053. A ring-sector polar grid running 5 cm cells inside 10 m and 50 cm at 100 m — " +
    "705,771 cells against 16,000,000 for a uniform grid over the same footprint — " +
    "preserving the curbs, potholes and overhangs a 2D occupancy grid destroys.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
