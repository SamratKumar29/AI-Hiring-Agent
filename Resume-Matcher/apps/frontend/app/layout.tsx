import type { Metadata } from 'next';
import localFont from 'next/font/local';
import './(default)/css/globals.css';

// Self-hosted fonts (Liberation Sans: metric-compatible with Arial, formal look) so the build and PDF
// export need no access to Google Fonts. Patched by AI-Hiring-Agent; see patches/resume-matcher-local-fonts.md.
const spaceGrotesk = localFont({
  variable: '--font-space-grotesk',
  src: [
    { path: './fonts/LiberationSans-Regular.ttf', weight: '400', style: 'normal' },
    { path: './fonts/LiberationSans-Bold.ttf', weight: '700', style: 'normal' },
  ],
  display: 'swap',
});

const geist = localFont({
  variable: '--font-geist',
  src: [
    { path: './fonts/LiberationSans-Regular.ttf', weight: '400', style: 'normal' },
    { path: './fonts/LiberationSans-Bold.ttf', weight: '700', style: 'normal' },
  ],
  display: 'swap',
});

export const metadata: Metadata = {
  title: 'Resume Matcher',
  description: 'Build your resume with Resume Matcher',
  applicationName: 'Resume Matcher',
  keywords: ['resume', 'matcher', 'job', 'application'],
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en-US" className="h-full" suppressHydrationWarning>
      <body
        className={`${geist.variable} ${spaceGrotesk.variable} antialiased bg-background text-ink-soft min-h-full`}
      >
        {children}
      </body>
    </html>
  );
}
