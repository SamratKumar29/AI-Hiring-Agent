# Resume-Matcher local patch (self-hosted fonts)

Resume-Matcher's frontend downloads Google Fonts at build time (next/font/google). Behind a proxy that Node's font
downloader does not use, the build fails and PDF export cannot work. This patch uses bundled Liberation Sans instead.

Apply (from repo root, after cloning Resume-Matcher):

    cp patches/resume-matcher/layout.tsx       Resume-Matcher/apps/frontend/app/layout.tsx
    cp patches/resume-matcher/next.config.ts   Resume-Matcher/apps/frontend/next.config.ts
    mkdir -p Resume-Matcher/apps/frontend/app/fonts && cp patches/resume-matcher/fonts/*.ttf Resume-Matcher/apps/frontend/app/fonts/
    rm -rf Resume-Matcher/apps/frontend/.next      # forces the one-time build on next use

`next.config.ts` also sets `typescript.ignoreBuildErrors` (Resume-Matcher's own test files fail type-checking).
The frontend is built/started automatically by `brain/tailor.py` (ports 8765 backend / 8766 frontend).
