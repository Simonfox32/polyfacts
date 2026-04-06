"use client";

import Link from "next/link";
import { useState } from "react";
import { useAuth } from "@/context/AuthContext";

interface Props {
  onSessionCreated: (sessionId: string) => void;
}

export function ClipUploader({ onSessionCreated }: Props) {
  const { user, token, loading, isAdmin } = useAuth();
  const [uploading, setUploading] = useState(false);
  const [pendingLabel, setPendingLabel] = useState("Uploading...");
  const [error, setError] = useState<string | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const [sourceUrl, setSourceUrl] = useState("");

  async function handleFileUpload(file: File) {
    setUploading(true);
    setPendingLabel("Uploading...");
    setError(null);

    const formData = new FormData();
    formData.append("file", file);
    formData.append("title", file.name);

    try {
      const res = await fetch("/api/clips", {
        method: "POST",
        body: formData,
        headers: token
          ? {
              Authorization: `Bearer ${token}`,
            }
          : undefined,
      });

      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || "Upload failed");
      }

      const data = await res.json();
      onSessionCreated(data.clip_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  }

  async function handleUrlSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const trimmedUrl = sourceUrl.trim();
    if (!trimmedUrl) {
      setError("Paste a valid video URL.");
      return;
    }

    setUploading(true);
    setPendingLabel("Downloading...");
    setError(null);

    const formData = new FormData();
    formData.append("source_url", trimmedUrl);

    try {
      const res = await fetch("/api/clips/url", {
        method: "POST",
        body: formData,
        headers: token
          ? {
              Authorization: `Bearer ${token}`,
            }
          : undefined,
      });

      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || "Unable to process URL");
      }

      const data = await res.json();
      setSourceUrl("");
      onSessionCreated(data.clip_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to process URL");
    } finally {
      setUploading(false);
    }
  }

  function handleDrop(event: React.DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragActive(false);
    const file = event.dataTransfer.files[0];
    if (file) {
      void handleFileUpload(file);
    }
  }

  return (
    <div className="space-y-5">
      <div
        onDragOver={(event) => {
          event.preventDefault();
          setDragActive(true);
        }}
        onDragLeave={() => setDragActive(false)}
        onDrop={handleDrop}
        className={`rounded-3xl border-2 border-dashed p-10 text-center transition-colors ${
          dragActive ? "border-red-400 bg-red-50" : "border-gray-300 bg-gray-50"
        } ${uploading ? "pointer-events-none opacity-60" : ""}`}
      >
        <div className="mb-4">
          <svg
            className="mx-auto h-12 w-12 text-gray-400"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={1.5}
              d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"
            />
          </svg>
        </div>

        <p className="mb-1 text-lg font-medium text-gray-950">
          {uploading ? pendingLabel : "Drop a political clip here"}
        </p>
        <p className="mb-5 text-sm text-gray-500">
          MP3, MP4, WAV, M4A, OGG, FLAC, WEBM, MOV
        </p>

        <label className="inline-flex cursor-pointer items-center rounded-full bg-black px-4 py-2 text-sm font-medium text-white transition hover:bg-gray-800">
          Choose file
          <input
            type="file"
            className="hidden"
            accept=".mp3,.mp4,.wav,.m4a,.ogg,.flac,.webm,.mov"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) {
                void handleFileUpload(file);
              }
            }}
          />
        </label>
      </div>

      <div className="rounded-3xl border border-gray-200 bg-white p-4 shadow-sm">
        <p className="text-sm font-medium text-gray-950">Or paste a video URL</p>
        <p className="mt-1 text-sm text-gray-500">
          Direct media links work immediately. YouTube URLs work when `yt-dlp` is available on the server.
        </p>

        <form onSubmit={handleUrlSubmit} className="mt-4 flex flex-col gap-3 sm:flex-row">
          <input
            type="url"
            value={sourceUrl}
            onChange={(event) => setSourceUrl(event.target.value)}
            placeholder="https://www.youtube.com/watch?v=..."
            className="h-11 flex-1 rounded-full border border-gray-300 bg-white px-4 text-sm text-gray-900 placeholder:text-gray-400"
            disabled={uploading}
          />
          <button
            type="submit"
            disabled={uploading}
            className="h-11 rounded-full bg-black px-5 text-sm font-medium text-white transition hover:bg-gray-800 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {uploading && pendingLabel === "Downloading..." ? "Downloading..." : "Import URL"}
          </button>
        </form>
      </div>

      {error && <p className="text-sm text-red-600">{error}</p>}
    </div>
  );
}
