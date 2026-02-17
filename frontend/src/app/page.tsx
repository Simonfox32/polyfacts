"use client";

import { useEffect, useState } from "react";
import { ClipUploader } from "@/components/ClipUploader";
import { SessionView } from "@/components/SessionView";

interface SessionSummary {
  session_id: string;
  title: string | null;
  status: string;
  duration_seconds: number | null;
  claims_count: number;
  created_at: string;
}

const VERDICT_STATUS_COLORS: Record<string, string> = {
  completed: "bg-green-100 text-green-800",
  processing: "bg-yellow-100 text-yellow-800",
  queued: "bg-gray-100 text-gray-800",
  failed: "bg-red-100 text-red-800",
};

export default function Home() {
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch("/api/sessions")
      .then((r) => r.json())
      .then((data) => setSessions(data))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  return (
    <main className="max-w-6xl mx-auto px-4 py-8">
      <header className="mb-8">
        <h1
          className="text-3xl font-bold tracking-tight cursor-pointer"
          onClick={() => setActiveSessionId(null)}
        >
          Polyfacts
        </h1>
        <p className="text-gray-500 mt-1">
          Evidence-backed fact-checking for political broadcasts
        </p>
      </header>

      {activeSessionId ? (
        <div>
          <button
            onClick={() => setActiveSessionId(null)}
            className="text-sm text-gray-500 hover:text-gray-700 mb-4"
          >
            &larr; Back to sessions
          </button>
          <SessionView sessionId={activeSessionId} />
        </div>
      ) : (
        <div className="space-y-8">
          {/* Existing sessions */}
          {!loading && sessions.length > 0 && (
            <div>
              <h2 className="text-lg font-semibold mb-3">Sessions</h2>
              <div className="space-y-2">
                {sessions.map((s) => (
                  <button
                    key={s.session_id}
                    onClick={() => setActiveSessionId(s.session_id)}
                    className="w-full text-left rounded-lg border border-gray-200 p-4 hover:border-gray-400 hover:shadow-sm transition-all"
                  >
                    <div className="flex items-center justify-between">
                      <div>
                        <p className="font-medium">
                          {s.title || s.session_id}
                        </p>
                        <p className="text-sm text-gray-500 mt-0.5">
                          {s.claims_count} claims
                          {s.duration_seconds
                            ? ` · ${Math.floor(s.duration_seconds / 60)}m ${s.duration_seconds % 60}s`
                            : ""}
                          {" · "}
                          {new Date(s.created_at).toLocaleDateString()}
                        </p>
                      </div>
                      <span
                        className={`text-xs font-medium px-2 py-1 rounded ${
                          VERDICT_STATUS_COLORS[s.status] || "bg-gray-100"
                        }`}
                      >
                        {s.status}
                      </span>
                    </div>
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Upload new clip */}
          <div>
            {sessions.length > 0 && (
              <h2 className="text-lg font-semibold mb-3">Upload new clip</h2>
            )}
            <ClipUploader
              onSessionCreated={(id) => {
                setActiveSessionId(id);
              }}
            />
          </div>
        </div>
      )}
    </main>
  );
}
