import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "GALANT | Control documental",
  description: "Revisión de respaldo de cotizaciones previsionales y F30-1.",
  robots: { index: false, follow: false },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="es">
      <body>{children}</body>
    </html>
  );
}
