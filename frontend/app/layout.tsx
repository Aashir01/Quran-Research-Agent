import type { Metadata, Viewport } from "next";
import { Inter, Amiri_Quran, Noto_Nastaliq_Urdu } from "next/font/google";
import "./globals.css";
import { NO_FLASH_SCRIPT, PrefsProvider } from "@/components/prefs";
import { ToastProvider } from "@/components/toast";
import { Shell } from "@/components/shell";

/**
 * Fonts are self-hosted through next/font rather than linked from a CDN. Three
 * reasons, in order of weight: an Arabic face arriving late reflows an entire
 * page of scripture; Nastaliq is large enough that a FOUT is a genuinely bad
 * reading experience; and a research tool for a religious corpus should not
 * report each of its readers to a third party on page load.
 */
const inter = Inter({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-inter",
});

const amiri = Amiri_Quran({
  subsets: ["arabic"],
  weight: "400",
  display: "swap",
  variable: "--font-amiri",
});

const nastaliq = Noto_Nastaliq_Urdu({
  subsets: ["arabic"],
  weight: ["400", "600"],
  display: "swap",
  variable: "--font-nastaliq",
});

export const metadata: Metadata = {
  title: {
    default: "Qur'an Research Agent",
    template: "%s · QRA",
  },
  description:
    "Deterministic corpus retrieval, hypothesis testing and agentic research over the Qur'an — every count exhaustive, every quotation rendered from the database.",
  manifest: "/manifest.json",
  appleWebApp: { capable: true, statusBarStyle: "black-translucent", title: "QRA" },
  formatDetection: { telephone: false },
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f7f5ef" },
    { media: "(prefers-color-scheme: dark)", color: "#0b0e0d" },
  ],
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      dir="ltr"
      className={`${inter.variable} ${amiri.variable} ${nastaliq.variable}`}
      suppressHydrationWarning
    >
      <head>
        {/* Applies the saved theme, density and direction before first paint. */}
        <script dangerouslySetInnerHTML={{ __html: NO_FLASH_SCRIPT }} />
      </head>
      <body>
        <PrefsProvider>
          <ToastProvider>
            <Shell>{children}</Shell>
          </ToastProvider>
        </PrefsProvider>
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
