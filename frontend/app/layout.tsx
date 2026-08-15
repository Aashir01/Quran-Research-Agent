import type { Metadata, Viewport } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "Quran Research Agent",
  description:
    "Deterministic corpus retrieval, hypothesis testing and agentic research over the Qur'an",
  manifest: "/manifest.json",
  appleWebApp: { capable: true, statusBarStyle: "black-translucent", title: "QRA" },
};

export const viewport: Viewport = {
  themeColor: "#0f1210",
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

const TABS = [
  { href: "/", label: "Search", icon: "⌕" },
  { href: "/workbench", label: "Workbench", icon: "⚖" },
  { href: "/patterns", label: "Patterns", icon: "◇" },
  { href: "/notes", label: "Notes", icon: "✎" },
  { href: "/research", label: "Research", icon: "◈" },
];

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <header className="topbar">
          <Link href="/" className="brand" style={{ color: "inherit" }}>
            Quran Research Agent <span>· قرآنی تحقیق</span>
          </Link>
          <Link href="/about" className="small muted">
            sources
          </Link>
        </header>
        <main className="shell">{children}</main>
        <nav className="tabbar">
          {TABS.map((tab) => (
            <Link key={tab.href} href={tab.href}>
              <span className="icon">{tab.icon}</span>
              {tab.label}
            </Link>
          ))}
        </nav>
        <script
          dangerouslySetInnerHTML={{
            __html: `if ("serviceWorker" in navigator) {
              window.addEventListener("load", () => navigator.serviceWorker.register("/sw.js").catch(() => {}));
            }`,
          }}
        />
      </body>
    </html>
  );
}
