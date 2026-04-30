"use client"
import { useEffect } from "react"
import { useRouter } from "next/navigation"
import Link from "next/link"
import { useAuthStore } from "@/lib/store"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const router   = useRouter()
  const { user, clearAuth } = useAuthStore()

  useEffect(() => {
    const token = localStorage.getItem("access_token")
    if (!token) router.push("/login")
  }, [router])

  const handleLogout = () => {
    clearAuth()
    router.push("/login")
  }

  return (
    <div className="min-h-screen bg-slate-50">
      {/* Navbar */}
      <nav className="bg-white border-b border-slate-200 px-6 py-3 flex items-center justify-between shadow-sm">
        <div className="flex items-center gap-6">
          <span className="text-xl font-bold text-slate-800">📝 MCQGen CS116</span>
          <div className="flex gap-2">
            <Link href="/dashboard">
              <Button variant="ghost" size="sm">🏠 Tổng quan</Button>
            </Link>
            <Link href="/dashboard/generate">
              <Button variant="ghost" size="sm">⚡ Sinh câu hỏi</Button>
            </Link>
            <Link href="/dashboard/admin"><Button variant="ghost" size="sm">⚙️ Admin</Button></Link>
            <Link href="/dashboard/history">
              <Button variant="ghost" size="sm">📋 Lịch sử</Button>
            </Link>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {user && (
            <>
              <span className="text-sm text-slate-600">{user.full_name}</span>
              <Badge variant={user.role === "teacher" ? "default" : "secondary"}>
                {user.role === "teacher" ? "Giảng viên" : "Sinh viên"}
              </Badge>
            </>
          )}
          <Button variant="outline" size="sm" onClick={handleLogout}>Đăng xuất</Button>
        </div>
      </nav>
      <main className="max-w-7xl mx-auto px-6 py-8">{children}</main>
    </div>
  )
}
