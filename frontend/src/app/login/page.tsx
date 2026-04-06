"use client";

import { FormEvent, Suspense, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuth } from "@/context/AuthContext";

type AuthMode = "signin" | "register";

function LoginPageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { user, loading, login, register } = useAuth();
  const [mode, setMode] = useState<AuthMode>("signin");
  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const redirectPath = useMemo(() => searchParams.get("next") || "/", [searchParams]);

  useEffect(() => {
    if (!loading && user) {
      router.replace(redirectPath);
    }
  }, [loading, redirectPath, router, user]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);

    try {
      if (mode === "signin") {
        await login(email, password);
      } else {
        await register(email, username, password);
      }
      router.push(redirectPath);
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Authentication failed");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="flex min-h-[calc(100vh-3.5rem)] items-center justify-center bg-[radial-gradient(circle_at_top,_rgba(239,68,68,0.14),_transparent_35%),linear-gradient(180deg,_#fafaf9_0%,_#f3f4f6_100%)] px-4 py-10 sm:px-6">
      <div className="grid w-full max-w-5xl gap-6 lg:grid-cols-[1.1fr_520px]">
        <section className="hidden rounded-[32px] bg-neutral-950 p-8 text-white shadow-2xl lg:block">
          <p className="text-xs font-semibold uppercase tracking-[0.35em] text-red-300">
            Polyfacts Account
          </p>
          <h1 className="mt-5 text-4xl font-bold tracking-tight">
            Save sessions, track what you watched, and build a personal fact-check library.
          </h1>
          <p className="mt-5 max-w-md text-sm leading-7 text-gray-300">
            Your account unlocks likes, saved clips, and watch history across the entire app. Admin
            accounts also get upload access.
          </p>
          <div className="mt-10 grid gap-4 text-sm text-gray-200">
            <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
              Likes keep important sessions one click away.
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
              Saved items behave like a lightweight watch-later queue.
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
              Watch history resumes long clips without losing your place.
            </div>
          </div>
        </section>

        <section className="rounded-[32px] bg-white p-6 shadow-xl ring-1 ring-black/5 sm:p-8">
          <div className="flex rounded-full bg-gray-100 p-1">
            <button
              type="button"
              onClick={() => {
                setMode("signin");
                setError(null);
              }}
              className={`flex-1 rounded-full px-4 py-2.5 text-sm font-semibold transition ${
                mode === "signin" ? "bg-white text-gray-950 shadow-sm" : "text-gray-500"
              }`}
            >
              Sign in
            </button>
            <button
              type="button"
              onClick={() => {
                setMode("register");
                setError(null);
              }}
              className={`flex-1 rounded-full px-4 py-2.5 text-sm font-semibold transition ${
                mode === "register" ? "bg-white text-gray-950 shadow-sm" : "text-gray-500"
              }`}
            >
              Create account
            </button>
          </div>

          <div className="mt-8">
            <h2 className="text-2xl font-bold tracking-tight text-gray-950">
              {mode === "signin" ? "Welcome back" : "Create your account"}
            </h2>
            <p className="mt-2 text-sm text-gray-500">
              {mode === "signin"
                ? "Sign in to like sessions, save clips, and sync watch history."
                : "Register to start building your personal Polyfacts library."}
            </p>
          </div>

          <form onSubmit={handleSubmit} className="mt-8 space-y-4">
            <label className="block">
              <span className="mb-2 block text-sm font-medium text-gray-700">Email</span>
              <input
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                required
                className="h-12 w-full rounded-2xl border border-gray-300 bg-white px-4 text-sm text-gray-900 outline-none transition focus:border-gray-500"
                placeholder="name@example.com"
              />
            </label>

            {mode === "register" && (
              <label className="block">
                <span className="mb-2 block text-sm font-medium text-gray-700">Username</span>
                <input
                  type="text"
                  value={username}
                  onChange={(event) => setUsername(event.target.value)}
                  required
                  minLength={3}
                  className="h-12 w-full rounded-2xl border border-gray-300 bg-white px-4 text-sm text-gray-900 outline-none transition focus:border-gray-500"
                  placeholder="Your public handle"
                />
              </label>
            )}

            <label className="block">
              <span className="mb-2 block text-sm font-medium text-gray-700">Password</span>
              <input
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
                minLength={mode === "register" ? 8 : 1}
                className="h-12 w-full rounded-2xl border border-gray-300 bg-white px-4 text-sm text-gray-900 outline-none transition focus:border-gray-500"
                placeholder={mode === "signin" ? "Enter your password" : "Use at least 8 characters"}
              />
            </label>

            {error && (
              <div className="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={loading || submitting}
              className="w-full rounded-2xl bg-black px-4 py-3 text-sm font-semibold text-white transition hover:bg-gray-800 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {submitting
                ? mode === "signin"
                  ? "Signing in..."
                  : "Creating account..."
                : mode === "signin"
                  ? "Sign in"
                  : "Create account"}
            </button>
          </form>

          <p className="mt-6 text-sm text-gray-500">
            Want to keep browsing first?{" "}
            <Link href="/" className="font-medium text-gray-900 underline decoration-gray-300">
              Return home
            </Link>
          </p>
        </section>
      </div>
    </main>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginPageInner />
    </Suspense>
  );
}
