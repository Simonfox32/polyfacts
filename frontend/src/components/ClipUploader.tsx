"use client";

import { useCallback, useState } from "react";

interface Props {
  onSessionCreated: (sessionId: string) => void;
}

export function ClipUploader({ onSessionCreated }: Props) {
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragActive, setDragActive] = useState(false);

  const handleUpload = useCallback(
    async (file: File) => {
      setUploading(true);
      setError(null);

      const formData = new FormData();
      formData.append("file", file);
      formData.append("title", file.name);

      try {
        const res = await fetch("/api/clips", {
          method: "POST",
          body: formData,
        });

        if (!res.ok) {
          const data = await res.json();
          throw new Error(data.detail || "Upload failed");
        }

        const data = await res.json();
        onSessionCreated(data.clip_id);
      } catch (err: any) {
        setError(err.message);
      } finally {
        setUploading(false);
      }
    },
    [onSessionCreated]
  );

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragActive(false);
      const file = e.dataTransfer.files[0];
      if (file) handleUpload(file);
    },
    [handleUpload]
  );

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setDragActive(true);
      }}
      onDragLeave={() => setDragActive(false)}
      onDrop={handleDrop}
      className={`
        border-2 border-dashed rounded-xl p-12 text-center transition-colors
        ${dragActive ? "border-blue-500 bg-blue-50" : "border-gray-300"}
        ${uploading ? "opacity-50 pointer-events-none" : ""}
      `}
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

      <p className="text-lg font-medium mb-1">
        {uploading ? "Uploading..." : "Drop a political clip here"}
      </p>
      <p className="text-sm text-gray-500 mb-4">
        MP3, MP4, WAV, M4A, OGG, FLAC (max 500MB)
      </p>

      <label className="inline-block cursor-pointer">
        <span className="px-4 py-2 bg-black text-white rounded-lg text-sm font-medium hover:bg-gray-800 transition-colors">
          Choose file
        </span>
        <input
          type="file"
          className="hidden"
          accept=".mp3,.mp4,.wav,.m4a,.ogg,.flac"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) handleUpload(file);
          }}
        />
      </label>

      {error && (
        <p className="mt-4 text-sm text-red-600">{error}</p>
      )}
    </div>
  );
}
