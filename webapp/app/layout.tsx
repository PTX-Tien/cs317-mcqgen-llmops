import type { Metadata } from "next"
import "./globals.css"
import { Toaster } from "@/components/ui/sonner"

export const metadata: Metadata = {
  title: "MCQGen CS116 — Hệ thống sinh câu hỏi trắc nghiệm",
  description: "Automatic MCQ Generation for CS116 — ĐH Công nghệ Thông tin ĐHQG-HCM",
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="vi" suppressHydrationWarning>
      <body className="font-sans" suppressHydrationWarning>
        {children}
        <Toaster richColors position="top-right" />
      </body>
    </html>
  )
}
