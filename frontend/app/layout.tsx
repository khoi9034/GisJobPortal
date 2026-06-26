import "./globals.css";

export const metadata = {
  title: "GIS Apply Copilot",
  description: "Human-reviewed GIS job application intelligence dashboard",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
