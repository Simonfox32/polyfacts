"use client";

import Link from "next/link";
import { FormEvent, Suspense, useEffect, useRef, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useAuth } from "@/context/AuthContext";

function NavBarInner() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { user, loading, logout, isAdmin } = useAuth();
  const menuRef = useRef<HTMLDivElement | null>(null);
  const [query, setQuery] = useState(searchParams.get("q") ?? "");
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    setQuery(searchParams.get("q") ?? "");
  }, [searchParams]);

  useEffect(() => {
    if (!menuOpen) return;

    function handleMouseDown(event: MouseEvent) {
      if (!menuRef.current?.contains(event.target as Node)) {
        setMenuOpen(false);
      }
    }

    window.addEventListener("mousedown", handleMouseDown);
    return () => {
      window.removeEventListener("mousedown", handleMouseDown);
    };
  }, [menuOpen]);

  useEffect(() => {
    setMenuOpen(false);
  }, [pathname]);

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    const trimmed = query.trim();
    const nextParams = new URLSearchParams();
    const sort = searchParams.get("sort");

    if (trimmed) {
      nextParams.set("q", trimmed);
    }

    if (sort) {
      nextParams.set("sort", sort);
    }

    const nextPath = nextParams.toString() ? `/?${nextParams.toString()}` : "/";
    if (pathname === "/" && nextPath === `${pathname}${window.location.search}`) {
      return;
    }

    router.push(nextPath);
  };

  return (
    <header className="fixed inset-x-0 top-0 z-50 border-b border-gray-200 bg-white/95 backdrop-blur">
      <div className="mx-auto flex h-14 max-w-[1440px] items-center gap-4 px-4 sm:px-6">
        <Link
          href="/"
          className="flex shrink-0 items-center gap-2 text-lg font-bold text-gray-950 transition-colors hover:text-gray-700"
        >
          <span className="flex h-8 w-8 items-center justify-center rounded-full bg-red-600 text-sm font-black text-white">
            P
          </span>
          <span>Polyfacts</span>
        </Link>

        <form onSubmit={handleSubmit} className="mx-auto flex w-full max-w-xl items-center">
          <div className="flex w-full items-center overflow-hidden rounded-full border border-gray-300 bg-white shadow-sm transition-colors focus-within:border-gray-400">
            <input
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search claims, speakers..."
              aria-label="Search claims or speakers"
              className="w-full border-0 bg-transparent px-4 py-2 text-sm text-gray-900 placeholder:text-gray-400 transition-colors focus:ring-0"
            />
            <button
              type="submit"
              className="flex h-10 w-12 items-center justify-center border-l border-gray-200 bg-gray-50 text-gray-600 transition-colors hover:bg-gray-100 hover:text-gray-900"
              aria-label="Submit search"
            >
              <svg viewBox="0 0 24 24" className="h-4 w-4 fill-current" aria-hidden="true">
                <path d="M10 4a6 6 0 1 0 3.874 10.582l4.772 4.772 1.414-1.414-4.772-4.772A6 6 0 0 0 10 4Zm0 2a4 4 0 1 1 0 8 4 4 0 0 1 0-8Z" />
              </svg>
            </button>
          </div>
        </form>

        <div className="flex min-w-[120px] items-center justify-end gap-3">
          {isAdmin && (
            <Link
              href="/#upload"
              className="shrink-0 rounded-full bg-black px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-gray-800"
            >
              Upload
            </Link>
          )}

          {!loading &&
            (user ? (
              <div ref={menuRef} className="relative">
                <button
                  type="button"
                  onClick={() => setMenuOpen((current) => !current)}
                  className="flex items-center gap-2 rounded-full border border-gray-200 bg-white px-2 py-1.5 shadow-sm transition-colors hover:border-gray-300 hover:bg-gray-50"
                  aria-haspopup="menu"
                  aria-expanded={menuOpen}
                >
                  <span className="flex h-8 w-8 items-center justify-center rounded-full bg-red-100 text-sm font-bold uppercase text-red-700">
                    {user.username[0] ?? "U"}
                  </span>
                  <span className="hidden max-w-24 truncate pr-2 text-sm font-medium text-gray-900 sm:block">
                    {user.username}
                  </span>
                </button>

                {menuOpen && (
                  <div className="absolute right-0 top-[calc(100%+0.5rem)] w-48 overflow-hidden rounded-2xl border border-gray-200 bg-white py-2 shadow-xl">
                    <Link
                      href="/library"
                      className="block px-4 py-2 text-sm text-gray-700 transition-colors hover:bg-gray-50 hover:text-gray-950"
                    >
                      Library
                    </Link>
                    <button
                      type="button"
                      onClick={() => {
                        logout();
                        setMenuOpen(false);
                        router.push("/");
                      }}
                      className="block w-full px-4 py-2 text-left text-sm text-gray-700 transition-colors hover:bg-gray-50 hover:text-gray-950"
                    >
                      Logout
                    </button>
                  </div>
                )}
              </div>
            ) : (
              <Link
                href="/login"
                className="shrink-0 rounded-full border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-900 transition-colors hover:border-gray-400 hover:bg-gray-50"
              >
                Sign in
              </Link>
            ))}
        </div>
      </div>
    </header>
  );
}

export function NavBar() {
  return (
    <Suspense fallback={null}>
      <NavBarInner />
    </Suspense>
  );
}
