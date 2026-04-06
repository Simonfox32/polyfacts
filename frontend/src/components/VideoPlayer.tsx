"use client";

import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";

type MediaType = "audio" | "video";

interface PlayerClaim {
  claim_id: string;
  start_ms: number;
  verdict_label: string | null;
}

export interface VideoPlayerHandle {
  seekTo: (ms: number) => void;
  seekRelative: (deltaMs: number) => void;
  togglePlayback: () => void;
  adjustVolume: (delta: number) => void;
  toggleMute: () => void;
  toggleFullscreen: () => void;
}

interface VideoPlayerProps {
  sessionId: string;
  mediaType: MediaType;
  durationSeconds: number | null;
  claims: PlayerClaim[];
  onTimeUpdate?: (currentMs: number) => void;
  onPlaybackStateChange?: (isPlaying: boolean) => void;
  onClaimClick?: (claimId: string) => void;
}

const PLAYBACK_SPEEDS = [0.5, 1, 1.5, 2];

const VERDICT_MARKER_COLORS: Record<string, string> = {
  TRUE: "bg-green-500",
  MOSTLY_TRUE: "bg-lime-500",
  HALF_TRUE: "bg-yellow-400",
  MOSTLY_FALSE: "bg-orange-500",
  FALSE: "bg-red-500",
  UNVERIFIED: "bg-slate-400",
};

export const VideoPlayer = forwardRef<VideoPlayerHandle, VideoPlayerProps>(
  function VideoPlayer(
    {
      sessionId,
      mediaType,
      durationSeconds,
      claims,
      onTimeUpdate,
      onPlaybackStateChange,
      onClaimClick,
    },
    ref
  ) {
    const mediaRef = useRef<HTMLMediaElement | null>(null);
    const playerShellRef = useRef<HTMLDivElement | null>(null);
    const idleTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

    const [isPlaying, setIsPlaying] = useState(false);
    const [isBuffering, setIsBuffering] = useState(false);
    const [isFullscreen, setIsFullscreen] = useState(false);
    const [controlsVisible, setControlsVisible] = useState(true);
    const [currentTime, setCurrentTime] = useState(0);
    const [playbackRate, setPlaybackRate] = useState(1);
    const [loadedDuration, setLoadedDuration] = useState(durationSeconds ?? 0);
    const [volume, setVolume] = useState(0.85);

    const totalDuration = loadedDuration || durationSeconds || 0;
    const sourceUrl = `/api/media/${sessionId}`;

    useImperativeHandle(
      ref,
      () => ({
        seekTo(ms: number) {
          if (!mediaRef.current) return;
          const nextTimeSeconds = Math.max(ms, 0) / 1000;
          mediaRef.current.currentTime = nextTimeSeconds;
          setCurrentTime(mediaRef.current.currentTime);
          onTimeUpdate?.(Math.round(mediaRef.current.currentTime * 1000));
        },
        seekRelative(deltaMs: number) {
          if (!mediaRef.current) return;
          const durationSeconds = Number.isFinite(mediaRef.current.duration)
            ? mediaRef.current.duration
            : totalDuration;
          const nextTimeSeconds = Math.min(
            Math.max(mediaRef.current.currentTime + deltaMs / 1000, 0),
            durationSeconds || 0
          );
          mediaRef.current.currentTime = nextTimeSeconds;
          setCurrentTime(nextTimeSeconds);
          onTimeUpdate?.(Math.round(nextTimeSeconds * 1000));
        },
        togglePlayback() {
          if (!mediaRef.current) return;

          if (mediaRef.current.paused) {
            void mediaRef.current.play().then(
              () => {
                setIsPlaying(true);
              },
              () => {
                setIsPlaying(false);
              }
            );
            return;
          }

          mediaRef.current.pause();
          setIsPlaying(false);
        },
        adjustVolume(delta: number) {
          if (!mediaRef.current) return;
          const nextVolume = Math.min(Math.max(mediaRef.current.volume + delta, 0), 1);
          mediaRef.current.volume = nextVolume;
          mediaRef.current.muted = nextVolume === 0;
          setVolume(nextVolume);
        },
        toggleMute() {
          if (!mediaRef.current) return;
          mediaRef.current.muted = !mediaRef.current.muted;
        },
        toggleFullscreen() {
          if (!playerShellRef.current) {
            return;
          }

          if (document.fullscreenElement) {
            void document.exitFullscreen();
            return;
          }

          void playerShellRef.current.requestFullscreen();
        },
      }),
      [onTimeUpdate, totalDuration]
    );

    useEffect(() => {
      if (!mediaRef.current) return;
      mediaRef.current.playbackRate = playbackRate;
    }, [playbackRate]);

    useEffect(() => {
      if (!mediaRef.current) return;
      mediaRef.current.volume = volume;
      mediaRef.current.muted = volume === 0;
    }, [volume]);

    useEffect(() => {
      setCurrentTime(0);
      setIsPlaying(false);
      setIsBuffering(false);
      setLoadedDuration(durationSeconds ?? 0);
      onPlaybackStateChange?.(false);
    }, [durationSeconds, onPlaybackStateChange, sessionId]);

    useEffect(() => {
      const handleFullscreenChange = () => {
        setIsFullscreen(Boolean(document.fullscreenElement));
      };

      document.addEventListener("fullscreenchange", handleFullscreenChange);
      return () => {
        document.removeEventListener("fullscreenchange", handleFullscreenChange);
      };
    }, []);

    useEffect(() => {
      if (isPlaying) {
        idleTimerRef.current = setTimeout(() => setControlsVisible(false), 3000);
      } else {
        setControlsVisible(true);
        if (idleTimerRef.current) clearTimeout(idleTimerRef.current);
      }
      return () => {
        if (idleTimerRef.current) clearTimeout(idleTimerRef.current);
      };
    }, [isPlaying]);

    function resetIdleTimer() {
      setControlsVisible(true);
      if (idleTimerRef.current) clearTimeout(idleTimerRef.current);
      if (isPlaying) {
        idleTimerRef.current = setTimeout(() => setControlsVisible(false), 3000);
      }
    }

    async function togglePlayback() {
      if (!mediaRef.current) return;

      if (mediaRef.current.paused) {
        try {
          await mediaRef.current.play();
          setIsPlaying(true);
        } catch {
          setIsPlaying(false);
        }
        return;
      }

      mediaRef.current.pause();
      setIsPlaying(false);
    }

    function handleSeek(nextSeconds: number) {
      if (!mediaRef.current) return;
      mediaRef.current.currentTime = nextSeconds;
      setCurrentTime(nextSeconds);
      onTimeUpdate?.(Math.round(nextSeconds * 1000));
    }

    function handleCycleSpeed() {
      const currentIndex = PLAYBACK_SPEEDS.indexOf(playbackRate);
      const nextRate = PLAYBACK_SPEEDS[(currentIndex + 1) % PLAYBACK_SPEEDS.length];
      setPlaybackRate(nextRate);
    }

    function handleClaimMarkerClick(claim: PlayerClaim) {
      handleSeek(claim.start_ms / 1000);
      onClaimClick?.(claim.claim_id);
    }

    async function toggleFullscreen() {
      if (!playerShellRef.current) {
        return;
      }

      if (document.fullscreenElement) {
        await document.exitFullscreen();
        return;
      }

      await playerShellRef.current.requestFullscreen();
    }

    return (
      <div
        ref={playerShellRef}
        className={
          isFullscreen
            ? "fixed inset-0 z-50 flex flex-col bg-black"
            : "overflow-hidden rounded-[24px] bg-black shadow-xl shadow-black/10"
        }
        onMouseMove={resetIdleTimer}
        onMouseEnter={() => setControlsVisible(true)}
        onMouseLeave={() => {
          if (isPlaying) {
            setControlsVisible(false);
          }
        }}
        style={isFullscreen && !controlsVisible ? { cursor: "none" } : undefined}
      >
        <div className={isFullscreen ? "relative flex-1 flex flex-col items-center justify-center bg-black" : "relative bg-black"}>
          {mediaType === "audio" && (
            <div className="flex aspect-video items-center justify-center bg-gradient-to-br from-gray-950 via-gray-900 to-black px-6">
              <div className="w-full max-w-3xl rounded-[24px] border border-white/10 bg-white/5 p-6 backdrop-blur">
                <div className="mb-4 flex items-center justify-between">
                  <div>
                    <p className="text-xs uppercase tracking-[0.3em] text-gray-500">Audio Session</p>
                    <p className="mt-1 text-sm text-gray-300">Transcript-synced fact-check playback</p>
                  </div>
                  <div className="rounded-full border border-white/15 px-3 py-1 text-xs text-gray-300">
                    {playbackRate}x
                  </div>
                </div>
                <div className="flex h-28 items-end gap-2">
                  {Array.from({ length: 32 }).map((_, index) => (
                    <div
                      key={index}
                      className="flex-1 rounded-t-full bg-gradient-to-t from-red-600 via-orange-400 to-amber-200 opacity-90"
                      style={{ height: `${28 + ((index * 17) % 64)}%` }}
                    />
                  ))}
                </div>
              </div>
            </div>
          )}

          {mediaType === "video" ? (
            <video
              ref={(node) => {
                mediaRef.current = node;
              }}
              onClick={togglePlayback}
              className={
                isFullscreen
                  ? "max-h-full max-w-full cursor-pointer bg-black object-contain"
                  : "aspect-video w-full cursor-pointer bg-black"
              }
              src={sourceUrl}
              preload="metadata"
              playsInline
              onLoadedMetadata={(event) => {
                if (Number.isFinite(event.currentTarget.duration)) {
                  setLoadedDuration(event.currentTarget.duration);
                }
              }}
              onTimeUpdate={(event) => {
                const nextTime = event.currentTarget.currentTime;
                setCurrentTime(nextTime);
                onTimeUpdate?.(Math.round(nextTime * 1000));
              }}
              onPlay={() => {
                setIsPlaying(true);
                setIsBuffering(false);
                onPlaybackStateChange?.(true);
              }}
              onPause={() => {
                setIsPlaying(false);
                onPlaybackStateChange?.(false);
              }}
              onEnded={() => {
                setIsPlaying(false);
                onPlaybackStateChange?.(false);
              }}
              onWaiting={() => setIsBuffering(true)}
              onPlaying={() => {
                setIsPlaying(true);
                setIsBuffering(false);
                onPlaybackStateChange?.(true);
              }}
              onCanPlay={() => setIsBuffering(false)}
            />
          ) : (
            <audio
              ref={(node) => {
                mediaRef.current = node;
              }}
              className="hidden"
              src={sourceUrl}
              preload="metadata"
              onLoadedMetadata={(event) => {
                if (Number.isFinite(event.currentTarget.duration)) {
                  setLoadedDuration(event.currentTarget.duration);
                }
              }}
              onTimeUpdate={(event) => {
                const nextTime = event.currentTarget.currentTime;
                setCurrentTime(nextTime);
                onTimeUpdate?.(Math.round(nextTime * 1000));
              }}
              onPlay={() => {
                setIsPlaying(true);
                setIsBuffering(false);
                onPlaybackStateChange?.(true);
              }}
              onPause={() => {
                setIsPlaying(false);
                onPlaybackStateChange?.(false);
              }}
              onEnded={() => {
                setIsPlaying(false);
                onPlaybackStateChange?.(false);
              }}
              onWaiting={() => setIsBuffering(true)}
              onPlaying={() => {
                setIsPlaying(true);
                setIsBuffering(false);
                onPlaybackStateChange?.(true);
              }}
              onCanPlay={() => setIsBuffering(false)}
            />
          )}

          <div
            className={`pointer-events-none absolute inset-0 bg-gradient-to-t from-black/65 via-transparent to-transparent transition-opacity duration-300 ${!controlsVisible ? "opacity-0" : ""}`}
          />

          {isBuffering && (
            <div className="absolute right-4 top-4 flex items-center gap-2 rounded-full bg-black/70 px-3 py-1.5 text-xs font-medium text-white backdrop-blur">
              <span className="h-2 w-2 animate-pulse rounded-full bg-red-500" />
              Buffering
            </div>
          )}

          <button
            type="button"
            onClick={togglePlayback}
            className={`absolute left-1/2 top-1/2 flex h-16 w-16 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full bg-black/70 text-white shadow-lg backdrop-blur transition hover:scale-105 hover:bg-black/80 ${!controlsVisible ? "pointer-events-none opacity-0 transition-opacity duration-300" : "transition-opacity duration-300"}`}
            aria-label={isPlaying ? "Pause playback" : "Start playback"}
          >
            {isPlaying ? (
              <svg viewBox="0 0 24 24" className="h-8 w-8 fill-current" aria-hidden="true">
                <path d="M7 5h3v14H7zm7 0h3v14h-3z" />
              </svg>
            ) : (
              <svg viewBox="0 0 24 24" className="ml-1 h-8 w-8 fill-current" aria-hidden="true">
                <path d="m8 5 11 7-11 7V5Z" />
              </svg>
            )}
          </button>

          <div
            className={
              isFullscreen
                ? `absolute bottom-0 left-0 right-0 space-y-4 bg-gradient-to-t from-black/90 via-black/60 to-transparent p-4 text-white transition-opacity duration-300 ${controlsVisible ? "opacity-100" : "opacity-0 pointer-events-none"}`
                : `space-y-4 bg-[#0f0f0f] p-4 text-white transition-opacity duration-300 ${controlsVisible ? "opacity-100" : "opacity-0 pointer-events-none"}`
            }
          >
            <div className="relative px-1 pt-3">
              <input
                type="range"
                min={0}
                max={Math.max(totalDuration, 0.1)}
                step={0.1}
                value={Math.min(currentTime, totalDuration || currentTime)}
                onChange={(event) => handleSeek(Number(event.target.value))}
                className="h-2 w-full cursor-pointer appearance-none rounded-full bg-white/20 accent-red-500 sm:h-1.5"
                aria-label="Seek timeline"
              />
              {totalDuration > 0 &&
                claims.map((claim) => {
                  const left = Math.min((claim.start_ms / 1000 / totalDuration) * 100, 100);
                  const markerClass =
                    VERDICT_MARKER_COLORS[claim.verdict_label || "UNVERIFIED"] || "bg-slate-400";

                  return (
                    <button
                      key={claim.claim_id}
                      type="button"
                      title={`Jump to ${formatTime(claim.start_ms / 1000)}`}
                      onClick={() => handleClaimMarkerClick(claim)}
                      className={`absolute top-0 h-4 w-4 -translate-x-1/2 rounded-full border border-white/80 ${markerClass} shadow sm:h-3.5 sm:w-3.5`}
                      style={{ left: `${left}%` }}
                    />
                  );
                })}
            </div>

            <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between">
              <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto sm:gap-3">
                <button
                  type="button"
                  onClick={togglePlayback}
                  className="min-h-11 rounded-full bg-white px-4 py-2.5 text-sm font-semibold text-black transition hover:bg-gray-200 sm:px-5"
                >
                  {isPlaying ? "Pause" : "Play"}
                </button>

                <div className="text-sm tabular-nums text-gray-300">
                  <span>{formatTime(currentTime)}</span>
                  <span className="hidden sm:inline"> / {formatTime(totalDuration)}</span>
                </div>
              </div>

              <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto sm:justify-end sm:gap-3">
                <label className="hidden min-h-11 items-center gap-3 rounded-full bg-white/5 px-3 py-2 text-sm text-gray-200 sm:flex">
                  <svg viewBox="0 0 24 24" className="h-4 w-4 fill-current" aria-hidden="true">
                    <path d="M14 5.23v13.54a1 1 0 0 1-1.64.77L8.7 16H5a1 1 0 0 1-1-1V9a1 1 0 0 1 1-1h3.7l3.66-3.54A1 1 0 0 1 14 5.23Zm3.78 1.1a1 1 0 0 1 1.41 0 8 8 0 0 1 0 11.32 1 1 0 0 1-1.41-1.42 6 6 0 0 0 0-8.48 1 1 0 0 1 0-1.42Z" />
                  </svg>
                  <input
                    type="range"
                    min={0}
                    max={1}
                    step={0.05}
                    value={volume}
                    onChange={(event) => setVolume(Number(event.target.value))}
                    className="h-1.5 w-24 cursor-pointer appearance-none rounded-full bg-white/20 accent-red-500"
                    aria-label="Volume"
                  />
                </label>

                <button
                  type="button"
                  onClick={handleCycleSpeed}
                  className="min-h-11 rounded-full border border-white/10 bg-white/5 px-3 py-2 text-sm font-medium text-gray-200 transition hover:border-white/20 hover:bg-white/10"
                >
                  Speed {playbackRate}x
                </button>

                {mediaType === "video" && (
                  <button
                    type="button"
                    onClick={toggleFullscreen}
                    className="min-h-11 rounded-full border border-white/10 bg-white/5 px-3 py-2 text-sm font-medium text-gray-200 transition hover:border-white/20 hover:bg-white/10"
                  >
                    {isFullscreen ? "Exit full screen" : "Full screen"}
                  </button>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }
);

function formatTime(totalSeconds: number): string {
  const safeSeconds = Number.isFinite(totalSeconds) ? Math.max(totalSeconds, 0) : 0;
  const seconds = Math.floor(safeSeconds);
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remainingSeconds = seconds % 60;

  if (hours > 0) {
    return `${hours}:${minutes.toString().padStart(2, "0")}:${remainingSeconds
      .toString()
      .padStart(2, "0")}`;
  }

  return `${minutes}:${remainingSeconds.toString().padStart(2, "0")}`;
}
