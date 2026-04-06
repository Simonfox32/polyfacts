"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/context/AuthContext";

interface CommentData {
  comment_id: string;
  user_id: string;
  username: string;
  text: string;
  like_count: number;
  dislike_count: number;
  is_deleted: boolean;
  user_vote: "like" | "dislike" | null;
  created_at: string | null;
  replies: CommentData[];
}

const PAGE_SIZE = 20;

function timeAgo(dateStr: string | null): string {
  if (!dateStr) return "";

  const seconds = Math.floor((Date.now() - new Date(dateStr).getTime()) / 1000);
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  if (seconds < 2592000) return `${Math.floor(seconds / 86400)}d ago`;

  return new Date(dateStr).toLocaleDateString();
}

function CommentItem({
  comment,
  sessionId,
  token,
  isReply = false,
  onUpdate,
}: {
  comment: CommentData;
  sessionId: string;
  token: string | null;
  isReply?: boolean;
  onUpdate: () => void;
}) {
  const [showReplyInput, setShowReplyInput] = useState(false);
  const [replyText, setReplyText] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const { user } = useAuth();

  const handleVote = useCallback(
    async (voteType: "like" | "dislike") => {
      if (!token) return;

      try {
        const response = await fetch(`/api/comments/${comment.comment_id}/vote`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify({ vote_type: voteType }),
        });

        if (response.ok) {
          onUpdate();
        }
      } catch {
        // Ignore transient vote failures in the UI.
      }
    },
    [comment.comment_id, onUpdate, token]
  );

  const handleReply = useCallback(async () => {
    if (!token || !replyText.trim()) return;

    setSubmitting(true);

    try {
      const response = await fetch(`/api/sessions/${sessionId}/comments`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          text: replyText.trim(),
          parent_id: comment.comment_id,
        }),
      });

      if (response.ok) {
        setReplyText("");
        setShowReplyInput(false);
        onUpdate();
      }
    } catch {
      // Ignore transient reply failures in the UI.
    } finally {
      setSubmitting(false);
    }
  }, [comment.comment_id, onUpdate, replyText, sessionId, token]);

  const handleDelete = useCallback(async () => {
    if (!token) return;

    try {
      const response = await fetch(`/api/comments/${comment.comment_id}`, {
        method: "DELETE",
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });

      if (response.ok) {
        onUpdate();
      }
    } catch {
      // Ignore transient delete failures in the UI.
    }
  }, [comment.comment_id, onUpdate, token]);

  const canDelete = (user?.user_id === comment.user_id || user?.is_admin) && !comment.is_deleted;
  const canReply = Boolean(token) && !isReply && !comment.is_deleted;

  return (
    <div className={`flex gap-3 ${isReply ? "ml-12 mt-3" : "mt-4"}`}>
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gray-200 text-sm font-semibold text-gray-600">
        {comment.username?.[0]?.toUpperCase() || "?"}
      </div>

      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-gray-900">{comment.username}</span>
          <span className="text-xs text-gray-400">{timeAgo(comment.created_at)}</span>
        </div>

        <p
          className={`mt-1 whitespace-pre-wrap text-sm ${
            comment.is_deleted ? "italic text-gray-400" : "text-gray-800"
          }`}
        >
          {comment.text}
        </p>

        <div className="mt-1.5 flex items-center gap-3">
          <button
            type="button"
            onClick={() => void handleVote("like")}
            disabled={!token}
            className={`flex items-center gap-1 text-xs disabled:cursor-not-allowed disabled:opacity-60 ${
              comment.user_vote === "like"
                ? "font-semibold text-blue-600"
                : "text-gray-500 hover:text-gray-700"
            }`}
            aria-label="Like comment"
          >
            <svg
              className="h-4 w-4"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2}
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M14 9V5a3 3 0 00-3-3l-4 9v11h11.28a2 2 0 002-1.7l1.38-9a2 2 0 00-2-2.3H14z"
              />
            </svg>
            {comment.like_count > 0 && comment.like_count}
          </button>

          <button
            type="button"
            onClick={() => void handleVote("dislike")}
            disabled={!token}
            className={`flex items-center gap-1 text-xs disabled:cursor-not-allowed disabled:opacity-60 ${
              comment.user_vote === "dislike"
                ? "font-semibold text-blue-600"
                : "text-gray-500 hover:text-gray-700"
            }`}
            aria-label="Dislike comment"
          >
            <svg
              className="h-4 w-4 rotate-180"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2}
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M14 9V5a3 3 0 00-3-3l-4 9v11h11.28a2 2 0 002-1.7l1.38-9a2 2 0 00-2-2.3H14z"
              />
            </svg>
            {comment.dislike_count > 0 && comment.dislike_count}
          </button>

          {canReply && (
            <button
              type="button"
              onClick={() => setShowReplyInput((current) => !current)}
              className="text-xs font-medium text-gray-500 hover:text-gray-700"
            >
              Reply
            </button>
          )}

          {canDelete && (
            <button
              type="button"
              onClick={() => void handleDelete()}
              className="text-xs text-gray-400 hover:text-red-500"
            >
              Delete
            </button>
          )}
        </div>

        {showReplyInput && (
          <div className="mt-2 flex gap-2">
            <input
              value={replyText}
              onChange={(event) => setReplyText(event.target.value)}
              placeholder="Add a reply..."
              className="flex-1 rounded-lg border border-gray-300 px-3 py-1.5 text-sm focus:border-blue-500 focus:outline-none"
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  void handleReply();
                }
              }}
            />
            <button
              type="button"
              onClick={() => void handleReply()}
              disabled={submitting || !replyText.trim()}
              className="rounded-full bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              Reply
            </button>
          </div>
        )}

        {comment.replies?.map((reply) => (
          <CommentItem
            key={reply.comment_id}
            comment={reply}
            sessionId={sessionId}
            token={token}
            isReply
            onUpdate={onUpdate}
          />
        ))}
      </div>
    </div>
  );
}

export function CommentsSection({ sessionId }: { sessionId: string }) {
  const { user, token } = useAuth();
  const [comments, setComments] = useState<CommentData[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState<"newest" | "top">("newest");
  const [newComment, setNewComment] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const fetchComments = useCallback(async (pageToLoad = page) => {
    try {
      const headers: Record<string, string> = {};
      if (token) {
        headers.Authorization = `Bearer ${token}`;
      }

      const params = new URLSearchParams({
        sort,
        page: "1",
        per_page: String(pageToLoad * PAGE_SIZE),
      });

      const response = await fetch(`/api/sessions/${sessionId}/comments?${params.toString()}`, {
        headers,
      });

      if (!response.ok) {
        return;
      }

      const data = await response.json();
      setComments(data.comments || []);
      setTotal(data.total || 0);
    } catch {
      // Ignore transient fetch failures and preserve current comments.
    }
  }, [page, sessionId, sort, token]);

  useEffect(() => {
    void fetchComments();
  }, [fetchComments]);

  const handleSubmit = useCallback(async () => {
    if (!token || !newComment.trim()) return;

    setSubmitting(true);

    try {
      const response = await fetch(`/api/sessions/${sessionId}/comments`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ text: newComment.trim() }),
      });

      if (response.ok) {
        setNewComment("");
        setPage(1);
        await fetchComments(1);
      }
    } catch {
      // Ignore transient submit failures in the UI.
    } finally {
      setSubmitting(false);
    }
  }, [fetchComments, newComment, sessionId, token]);

  return (
    <section className="mt-8 rounded-[28px] bg-white p-6 shadow-sm ring-1 ring-black/5">
      <div className="mb-4 flex items-center justify-between gap-3">
        <h2 className="text-lg font-semibold text-gray-950">
          {total} Comment{total !== 1 ? "s" : ""}
        </h2>

        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => {
              setSort("newest");
              setPage(1);
            }}
            className={`rounded-full px-3 py-1 text-xs font-medium ${
              sort === "newest"
                ? "bg-gray-900 text-white"
                : "bg-gray-100 text-gray-600 hover:bg-gray-200"
            }`}
          >
            Newest
          </button>
          <button
            type="button"
            onClick={() => {
              setSort("top");
              setPage(1);
            }}
            className={`rounded-full px-3 py-1 text-xs font-medium ${
              sort === "top"
                ? "bg-gray-900 text-white"
                : "bg-gray-100 text-gray-600 hover:bg-gray-200"
            }`}
          >
            Top
          </button>
        </div>
      </div>

      {token ? (
        <div className="mb-6 flex gap-3">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-blue-100 text-sm font-semibold text-blue-700">
            {user?.username?.[0]?.toUpperCase() || "?"}
          </div>

          <div className="flex-1">
            <textarea
              value={newComment}
              onChange={(event) => setNewComment(event.target.value)}
              placeholder="Add a comment..."
              rows={2}
              className="w-full resize-none rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
            />

            <div className="mt-2 flex justify-end gap-2">
              {newComment && (
                <button
                  type="button"
                  onClick={() => setNewComment("")}
                  className="rounded-full px-4 py-1.5 text-sm font-medium text-gray-600 hover:bg-gray-100"
                >
                  Cancel
                </button>
              )}

              <button
                type="button"
                onClick={() => void handleSubmit()}
                disabled={submitting || !newComment.trim()}
                className="rounded-full bg-blue-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
              >
                Comment
              </button>
            </div>
          </div>
        </div>
      ) : (
        <div className="mb-6 rounded-2xl bg-gray-50 p-4 text-center">
          <p className="text-sm text-gray-600">
            <Link href="/login" className="font-medium text-blue-600 hover:text-blue-800">
              Sign in
            </Link>{" "}
            to leave a comment
          </p>
        </div>
      )}

      <div>
        {comments.length === 0 ? (
          <p className="text-sm text-gray-500">No comments yet.</p>
        ) : (
          comments.map((comment) => (
            <CommentItem
              key={comment.comment_id}
              comment={comment}
              sessionId={sessionId}
              token={token}
              onUpdate={() => void fetchComments()}
            />
          ))
        )}
      </div>

      {comments.length < total && (
        <button
          type="button"
          onClick={() => setPage((current) => current + 1)}
          className="mt-4 w-full rounded-lg border border-gray-200 py-2 text-sm font-medium text-gray-600 hover:bg-gray-50"
        >
          Show more comments
        </button>
      )}
    </section>
  );
}
