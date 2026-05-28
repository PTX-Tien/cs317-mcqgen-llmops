"use client";

import { useEffect, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import Link from "next/link";
import {
  LayoutDashboard,
  Zap,
  History,
  Shield,
  Sun,
  Moon,
  Menu,
  LogOut,
} from "lucide-react";

import { useAuthStore } from "@/lib/store";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

const NAV_ITEMS = [
  { href: "/dashboard", label: "Tổng quan", icon: LayoutDashboard },
  { href: "/dashboard/generate", label: "Sinh câu hỏi", icon: Zap },
  { href: "/dashboard/history", label: "Lịch sử", icon: History },
];

const SYSTEM_ITEMS = [
  { href: "/dashboard/admin", label: "Admin", icon: Shield },
];

function NavItem({
  href,
  label,
  icon: Icon,
  isActive,
  sidebarOpen,
}: {
  href: string;
  label: string;
  icon: React.ElementType;
  isActive: boolean;
  sidebarOpen: boolean;
}) {
  return (
    <Link href={href} title={!sidebarOpen ? label : undefined}>
      <div
        className={`
          flex items-center rounded-2xl py-3 cursor-pointer
          transition-all duration-200
          ${sidebarOpen ? "gap-3 px-4 justify-start" : "justify-center px-0"}
          ${
            isActive
              ? "bg-gradient-to-r from-[#0B5CFF] to-[#1E7FFF] shadow-blue-500/30 text-white"
              : "hover:bg-white/10 text-white/80 hover:text-white"
          }
        `}
      >
        <Icon size={20} className="shrink-0" />
        {sidebarOpen && (
          <span className="whitespace-nowrap text-sm font-medium">{label}</span>
        )}
      </div>
    </Link>
  );
}

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const { user, clearAuth } = useAuthStore();
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [darkMode, setDarkMode] = useState(false);

  // Determine active route: exact match for /dashboard, prefix match for others
  const isActive = (href: string) => {
    if (href === "/dashboard") return pathname === "/dashboard";
    return pathname.startsWith(href);
  };

  useEffect(() => {
    const token = localStorage.getItem("access_token");
    if (!token) router.push("/login");
  }, [router]);

  useEffect(() => {
    document.body.classList.toggle("dark", darkMode);
  }, [darkMode]);

  const handleLogout = () => {
    clearAuth();
    router.push("/login");
  };

  return (
    <div className="flex h-screen overflow-hidden bg-[#F4F7FC] dark:bg-slate-900">
      {/* ───────────── Sidebar ───────────── */}
      <aside
        className={`
          ${sidebarOpen ? "w-[270px]" : "w-[76px]"}
          bg-gradient-to-b from-[#001B4D] to-[#001133]
          text-white flex flex-col shadow-2xl
          sticky top-0 z-50 h-screen transition-all duration-300 ease-in-out overflow-hidden shrink-0
        `}
      >
        {/* Logo */}
        <div className="px-5 py-6 border-b border-white/10 flex items-center gap-3 min-h-[88px]">
          <div className="w-10 h-10 rounded-2xl flex items-center justify-center text-2xl shadow-lg">
            📝
          </div>
          {sidebarOpen && (
            <div className="overflow-hidden">
              <h1 className="text-2xl font-extrabold tracking-tight leading-tight whitespace-nowrap">
                MCQGen CS116
              </h1>
            </div>
          )}
        </div>

        {/* Menu items */}
        <div className="flex-1 px-3 py-5 space-y-1 overflow-y-auto overflow-x-hidden">
          {sidebarOpen && (
            <p className="text-xs uppercase tracking-widest text-blue-200/60 px-3 mb-3">
              Menu
            </p>
          )}

          {NAV_ITEMS.map(({ href, label, icon }) => (
            <NavItem
              key={href}
              href={href}
              label={label}
              icon={icon}
              isActive={isActive(href)}
              sidebarOpen={sidebarOpen}
            />
          ))}

          <div className="pt-4">
            {sidebarOpen && (
              <p className="text-xs uppercase tracking-widest text-blue-200/60 px-3 mb-3">
                Hệ thống
              </p>
            )}
            {!sidebarOpen && <div className="border-t border-white/10 my-3" />}

            {SYSTEM_ITEMS.map(({ href, label, icon }) => (
              <NavItem
                key={href}
                href={href}
                label={label}
                icon={icon}
                isActive={isActive(href)}
                sidebarOpen={sidebarOpen}
              />
            ))}
          </div>
        </div>

        {/* Footer card */}
        {sidebarOpen && (
          <div className="p-4 shrink-0">
            <div className="rounded-3xl bg-gradient-to-r from-[#0B5CFF] to-[#00B8D9] p-5 shadow-xl">
              <h3 className="font-bold text-base">MCQGen CS116</h3>
              <p className="text-xs text-blue-100 mt-1">
                Hệ thống tạo câu hỏi trắc nghiệm bằng AI
              </p>
            </div>
          </div>
        )}
      </aside>

      {/* ───────────── Main ───────────── */}
      <div className="flex-1 flex min-h-0 flex-col min-w-0">
        {/* Top navbar */}
        <nav className="sticky top-0 z-40 h-[88px] bg-white dark:bg-slate-800 border-b border-slate-200 dark:border-slate-700 px-8 flex items-center justify-between shadow-sm shrink-0">
          {/* Burger button */}
          <button
            onClick={() => setSidebarOpen((prev) => !prev)}
            className="p-2 rounded-xl hover:bg-slate-100 dark:hover:bg-slate-700 transition"
            aria-label={sidebarOpen ? "Thu sidebar" : "Mở sidebar"}
          >
            <Menu size={22} className="text-slate-600 dark:text-slate-300" />
          </button>

          {/* Right actions */}
          <div className="flex items-center gap-4">
            {/* Dark mode toggle */}
            <button
              onClick={() => setDarkMode((prev) => !prev)}
              className="rounded-full p-2 text-slate-500 dark:text-slate-300 transition hover:bg-slate-100 dark:hover:bg-slate-700"
              aria-label="Toggle dark mode"
            >
              {darkMode ? <Sun size={20} /> : <Moon size={20} />}
            </button>

            <div className="h-8 w-px bg-slate-200 dark:bg-slate-600" />

            {user && (
              <>
                <div className="text-right">
                  <p className="text-sm font-semibold text-slate-700 dark:text-slate-200">
                    {user.full_name}
                  </p>
                  <p className="text-xs text-slate-400">MCQGen CS116</p>
                </div>

                <Badge className="rounded-full bg-blue-100 px-4 py-1 text-blue-700 hover:bg-blue-100">
                  {user.role === "teacher" ? "Giảng viên" : "Sinh viên"}
                </Badge>

                <div className="flex h-10 w-10 items-center justify-center rounded-full bg-[#E8F0FF] font-bold text-[#1E4FFF] shrink-0">
                  {user.full_name?.charAt(0).toUpperCase() || "G"}
                </div>
              </>
            )}

            <Button
              onClick={handleLogout}
              variant="outline"
              className="rounded-xl border-slate-200 dark:border-slate-600 dark:text-slate-200 dark:hover:bg-slate-700 gap-2"
            >
              <LogOut size={15} />
              Đăng xuất
            </Button>
          </div>
        </nav>

        {/* Content */}
        <main className="min-h-0 flex-1 overflow-y-auto px-8 py-8">{children}</main>
      </div>
    </div>
  );
}
