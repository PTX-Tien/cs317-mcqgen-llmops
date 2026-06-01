"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import {
  Sparkles,
  History,
  BrainCircuit,
  Activity,
  Cpu,
  ArrowRight,
  BookOpen,
  BarChart3,
  Wrench,
  Database,
  Monitor,
} from "lucide-react";

import { useAuthStore } from "@/lib/store";
import { api } from "@/lib/api";

import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

interface QueueStatus {
  status: "idle" | "busy";
  pending_jobs: number;
  active_jobs?: number;
  queued_jobs?: number;
  estimated_wait_min: number;
}

export default function DashboardPage() {
  const router = useRouter();
  const { user, setAuth } = useAuthStore();

  const [queueStatus, setQueueStatus] = useState<QueueStatus | null>(null);

  useEffect(() => {
    const token = localStorage.getItem("access_token");

    if (!token) {
      router.push("/login");
      return;
    }

    if (!user) {
      api
        .get("/auth/me")
        .then(({ data }) => {
          setAuth(
            {
              username: data.username,
              role: data.role,
              full_name: data.full_name,
            },
            token,
          );
        })
        .catch(() => router.push("/login"));
    }

    api
      .get("/queue/status")
      .then(({ data }) => setQueueStatus(data))
      .catch(() => {});
  }, [router, setAuth, user]);

  const pendingJobs = queueStatus?.pending_jobs ?? 0;
  const isQueueIdle = queueStatus?.status === "idle";

  return (
    <div className="space-y-5">
      {/* HERO — full width */}
      <Card className="rounded-3xl border border-slate-200 bg-white shadow-sm overflow-hidden">
        <CardContent className="px-8 py-5 flex items-center justify-between gap-6">
          <div className="flex items-center gap-4">
            <div className="text-4xl shrink-0">👋</div>
            <div>
              <h1 className="text-2xl font-bold text-slate-900">
                Xin chào, {user?.full_name || "..."}
              </h1>
              <p className="mt-1 text-slate-500 text-sm leading-5 max-w-md">
                Hệ thống sinh câu hỏi trắc nghiệm tự động cho môn CS116 sử dụng
                RAG pipeline và LLM inference.
              </p>
            </div>
          </div>
          {/* Decorative illustration */}
          <div className="hidden lg:flex items-center justify-center shrink-0 w-36 h-20 relative select-none pointer-events-none">
            <div className="text-[64px] drop-shadow-xl">🎓</div>
          </div>
        </CardContent>
      </Card>

      {/* SYSTEM STATUS — flat row */}
      <Card className="rounded-3xl border border-slate-200 bg-white shadow-sm">
        <CardContent className="px-8 py-2">
          <div className="grid grid-cols-4 divide-x divide-slate-100">
            <div className="flex items-center gap-4 pr-8">
              <div className="rounded-2xl bg-indigo-50 p-3 shrink-0">
                <Activity className="h-6 w-6 text-indigo-500" />
              </div>
              <div>
                <p className="text-xs text-slate-400 mb-0.5">Queue</p>
                <p className="text-base font-bold text-emerald-500 flex items-center gap-1.5">
                  {isQueueIdle ? "Ready" : `${pendingJobs} Jobs`}
                  {isQueueIdle && (
                    <span className="inline-block h-2 w-2 rounded-full bg-emerald-500" />
                  )}
                </p>
              </div>
            </div>

            <div className="flex items-center gap-4 px-8">
              <div className="rounded-2xl bg-violet-50 p-3 shrink-0">
                <BrainCircuit className="h-6 w-6 text-violet-500" />
              </div>
              <div>
                <p className="text-xs text-slate-400 mb-0.5">LLM</p>
                <p className="text-base font-bold text-slate-800">Qwen2.5-7B</p>
              </div>
            </div>

            <div className="flex items-center gap-4 px-8">
              <div className="rounded-2xl bg-emerald-50 p-3 shrink-0">
                <Sparkles className="h-6 w-6 text-emerald-500" />
              </div>
              <div>
                <p className="text-xs text-slate-400 mb-0.5">Retrieval</p>
                <p className="text-base font-bold text-slate-800">
                  Adaptive RAG
                </p>
              </div>
            </div>

            <div className="flex items-center gap-4 pl-8">
              <div className="rounded-2xl bg-cyan-50 p-3 shrink-0">
                <Cpu className="h-6 w-6 text-cyan-500" />
              </div>
              <div>
                <p className="text-xs text-slate-400 mb-0.5">GPU</p>
                <p className="text-base font-bold text-slate-800">
                  RTX 2080 Ti 11GB
                </p>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* MIDDLE ROW */}
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        {/* GENERATE CARD */}
        <Card className="rounded-3xl border border-slate-200 bg-[#F5F3FF] shadow-sm overflow-hidden">
          <CardContent className="px-7 py-2 flex items-center justify-between gap-4">
            <div className="flex-1">
              <div className="flex items-center gap-3 mb-2">
                <Sparkles className="h-5 w-5 text-violet-500 shrink-0" />
                <h2 className="text-lg font-bold text-slate-900">
                  Sinh câu hỏi mới
                </h2>
              </div>
              <p className="text-sm text-slate-500 leading-6 mb-5">
                Tạo bộ câu hỏi trắc nghiệm từ topic, độ khó, và learning outcome
                của môn học.
              </p>
              <Link href="/dashboard/generate">
                <Button className="rounded-full border border-violet-400 bg-transparent text-violet-700 hover:bg-violet-50 font-semibold px-5 gap-2 shadow-none">
                  Bắt đầu sinh câu hỏi
                  <ArrowRight className="h-4 w-4" />
                </Button>
              </Link>
            </div>
            <div className="hidden md:flex items-center justify-center shrink-0 w-20 h-20 select-none pointer-events-none">
              <div className="text-[56px]">📋</div>
            </div>
          </CardContent>
        </Card>

        {/* HISTORY SHORTCUT */}
        <Card className="rounded-3xl border border-slate-200 bg-white shadow-sm">
          <CardContent className="px-7 py-6 flex flex-col justify-between h-full">
            <div>
              <div className="flex items-center gap-2 mb-2">
                <History className="h-5 w-5 text-emerald-500" />
                <h3 className="text-lg font-bold text-slate-900">
                  Lịch sử tạo đề
                </h3>
              </div>
              <p className="text-sm text-slate-500 leading-6">
                Xem lại toàn bộ các đề thi đã được sinh trước đó, bao gồm nội
                dung, cấu hình và trạng thái xử lý.
              </p>
            </div>
            <div className="mt-5">
              <Link href="/dashboard/history">
                <Button className="rounded-full border border-slate-300 bg-transparent text-slate-700 hover:bg-slate-50 font-semibold px-5 gap-2 shadow-none">
                  Xem lịch sử tạo đề
                  <ArrowRight className="h-4 w-4" />
                </Button>
              </Link>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* BOTTOM ROW: System Overview + System Tools */}
      {/* SYSTEM TOOLS */}
      <Card className="rounded-3xl border border-slate-200 bg-white shadow-sm">
        <CardContent className="px-8 py-2">
          <div className="flex items-center gap-2 mb-3">
            <Wrench className="h-5 w-5 text-slate-500" />
            <h3 className="text-base font-semibold text-slate-800">
              System Tools
            </h3>
          </div>
          <div className="flex flex-wrap gap-3">
            <a href="http://192.168.20.154:8080/docs" target="_blank">
              <Button
                variant="outline"
                className="rounded-xl border-slate-200 gap-2 text-sm"
              >
                <BookOpen className="h-4 w-4 text-slate-500" />
                API Docs
              </Button>
            </a>
            <a href="http://192.168.20.154:6006" target="_blank">
              <Button
                variant="outline"
                className="rounded-xl border-slate-200 gap-2 text-sm"
              >
                <BarChart3 className="h-4 w-4 text-orange-500" />
                Phoenix
              </Button>
            </a>
            <a href="http://192.168.20.154:3001" target="_blank">
              <Button
                variant="outline"
                className="rounded-xl border-slate-200 gap-2 text-sm"
              >
                <Database className="h-4 w-4 text-emerald-500" />
                Grafana
              </Button>
            </a>
            <a href="http://192.168.20.154:5555" target="_blank">
              <Button
                variant="outline"
                className="rounded-xl border-slate-200 gap-2 text-sm"
              >
                <BrainCircuit className="h-4 w-4 text-violet-500" />
                Flower Queue
              </Button>
            </a>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
