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
    <div className="space-y-8 bg-slate-50 min-h-screen p-1">
      {/* HERO */}
      <div className="rounded-3xl border border-slate-200 bg-white p-8 shadow-sm">
        <div className="flex items-start justify-between flex-wrap gap-4">
          <div className="space-y-3">
            <div className="inline-flex items-center gap-2 rounded-full border border-indigo-100 bg-indigo-50 px-3 py-1 text-sm font-medium text-indigo-700">
              <Sparkles className="h-4 w-4" />
              AI MCQ Generation Platform
            </div>

            <div>
              <h1 className="text-4xl font-bold tracking-tight text-slate-900">
                Xin chào, {user?.full_name || "..."}
              </h1>

              <p className="mt-2 max-w-2xl text-slate-500 text-lg">
                Hệ thống sinh câu hỏi trắc nghiệm tự động cho môn CS116 sử dụng
                RAG pipeline và LLM inference.
              </p>
            </div>
          </div>

          <div className="rounded-2xl border border-slate-200 bg-slate-50 px-5 py-4">
            <div className="flex items-center gap-3">
              <div
                className={`h-3 w-3 rounded-full ${
                  isQueueIdle ? "bg-emerald-500" : "bg-amber-500"
                }`}
              />

              <div>
                <p className="text-sm text-slate-500">System Status</p>

                <p className="font-semibold text-slate-900">
                  {isQueueIdle
                    ? "Ready for generation"
                    : `${pendingJobs} jobs pending`}
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* STATS */}
      <div className="grid grid-cols-1 gap-5 md:grid-cols-3">
        <Card className="rounded-3xl border border-slate-200 bg-white shadow-sm">
          <CardContent className="p-6">
            <div className="mb-5 flex items-center justify-between">
              <div className="rounded-2xl bg-indigo-50 p-3">
                <Activity className="h-6 w-6 text-indigo-600" />
              </div>

              <span className="text-sm font-medium text-slate-400">Queue</span>
            </div>

            <h3 className="text-2xl font-bold text-slate-900">
              {isQueueIdle ? "Sẵn sàng" : `${pendingJobs} Jobs`}
            </h3>

            <p className="mt-2 text-sm leading-6 text-slate-500">
              {pendingJobs > 0
                ? `Đang chạy ${queueStatus?.active_jobs || 0} • 
                   Đang chờ ${queueStatus?.queued_jobs || 0}`
                : "Hệ thống hiện không có tác vụ chờ."}
            </p>
          </CardContent>
        </Card>

        <Card className="rounded-3xl border border-slate-200 bg-white shadow-sm">
          <CardContent className="p-6">
            <div className="mb-5 flex items-center justify-between">
              <div className="rounded-2xl bg-violet-50 p-3">
                <Cpu className="h-6 w-6 text-violet-600" />
              </div>

              <span className="text-sm font-medium text-slate-400">LLM</span>
            </div>

            <h3 className="text-2xl font-bold text-slate-900">Qwen2.5-7B</h3>

            <p className="mt-2 text-sm leading-6 text-slate-500">
              RTX 2080 Ti 11GB • Optimized inference pipeline
            </p>
          </CardContent>
        </Card>

        <Card className="rounded-3xl border border-slate-200 bg-white shadow-sm">
          <CardContent className="p-6">
            <div className="mb-5 flex items-center justify-between">
              <div className="rounded-2xl bg-emerald-50 p-3">
                <BrainCircuit className="h-6 w-6 text-emerald-600" />
              </div>

              <span className="text-sm font-medium text-slate-400">
                Retrieval
              </span>
            </div>

            <h3 className="text-2xl font-bold text-slate-900">Adaptive RAG</h3>

            <p className="mt-2 text-sm leading-6 text-slate-500">
              HyDE + Semantic Window + CrossEncoder reranking
            </p>
          </CardContent>
        </Card>
      </div>

      {/* ACTIONS */}
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
        {/* PRIMARY ACTION */}
        <Card className="lg:col-span-2 overflow-hidden rounded-3xl border-0 bg-gradient-to-br from-indigo-600 to-violet-600 shadow-xl">
          <CardContent className="p-8 text-white">
            <div className="flex h-full flex-col justify-between">
              <div>
                <div className="mb-6 inline-flex rounded-2xl bg-white/10 p-4 backdrop-blur">
                  <Sparkles className="h-8 w-8" />
                </div>

                <h2 className="text-3xl font-bold">Sinh câu hỏi mới</h2>

                <p className="mt-3 max-w-xl text-indigo-100 leading-7">
                  Tạo bộ câu hỏi trắc nghiệm tự động từ topic, độ khó và
                  learning outcome của môn học.
                </p>
              </div>

              <div className="mt-8">
                <Link href="/dashboard/generate">
                  <Button
                    className="
                      h-12 rounded-xl bg-white px-6 text-indigo-700
                      hover:bg-slate-100 font-semibold
                    "
                  >
                    Bắt đầu sinh câu hỏi
                    <ArrowRight className="ml-2 h-4 w-4" />
                  </Button>
                </Link>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* HISTORY */}
        <Card className="rounded-3xl border border-slate-200 bg-white shadow-sm transition-all hover:shadow-md">
          <CardContent className="flex h-full flex-col justify-between p-8">
            <div>
              <div className="mb-6 inline-flex rounded-2xl bg-slate-100 p-4">
                <History className="h-7 w-7 text-slate-700" />
              </div>

              <h2 className="text-2xl font-bold text-slate-900">
                Lịch sử đề thi
              </h2>

              <p className="mt-3 leading-7 text-slate-500">
                Xem, tải lại và quản lý các đề thi đã được sinh trước đó.
              </p>
            </div>

            <div className="mt-8">
              <Link href="/dashboard/history">
                <Button variant="outline" className="h-12 w-full rounded-xl">
                  Xem lịch sử
                </Button>
              </Link>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* SYSTEM LINKS */}
      <Card className="rounded-3xl border border-slate-200 bg-white shadow-sm">
        <CardContent className="p-6">
          <div className="mb-5">
            <h3 className="text-lg font-semibold text-slate-900">
              System Tools
            </h3>

            <p className="mt-1 text-sm text-slate-500">
              Monitoring và debugging cho hệ thống backend.
            </p>
          </div>

          <div className="flex flex-wrap gap-3">
            <a href="http://192.168.20.154:8080/docs" target="_blank">
              <Button variant="outline" className="rounded-xl border-slate-200">
                <Wrench className="mr-2 h-4 w-4" />
                API Docs
              </Button>
            </a>

            <a href="http://192.168.20.154:6006" target="_blank">
              <Button variant="outline" className="rounded-xl border-slate-200">
                <BarChart3 className="mr-2 h-4 w-4" />
                Phoenix
              </Button>
            </a>

            <a href="http://192.168.20.154:3001" target="_blank">
              <Button variant="outline" className="rounded-xl border-slate-200">
                <Database className="mr-2 h-4 w-4" />
                Grafana
              </Button>
            </a>

            <a href="http://192.168.20.154:5555" target="_blank">
              <Button variant="outline" className="rounded-xl border-slate-200">
                <BookOpen className="mr-2 h-4 w-4" />
                Flower Queue
              </Button>
            </a>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
