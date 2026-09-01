"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { api, ApiError, type FeedDto, type PostDto } from "@/lib/api";
import { PostCard } from "@/components/community";
import { Composer } from "@/components/composer";
import { CountUp, EmptyState, ErrorNote, Notice, Segmented, SkeletonCard } from "@/components/ui";
import { Stat } from "@/components/primitives";
import { Icon } from "@/components/icons";
import { usePrefs } from "@/components/prefs";

/**
 * The commons.
 *
 * A feed is a ranked list, so it carries the same label every other ranked
 * surface in this app carries. The distinction the sort tabs draw is between
 * *popularity* (useful, discussed) and *checkability* (evidence) — never
 * between true and false, which no ordering can express.
 */
export default function CommunityPage() {
  return (
    <Suspense fallback={<FeedSkeleton />}>
      <Feed />
    </Suspense>
  );
}

type Sort = "new" | "useful" | "evidence" | "discussed";

function Feed() {
  const params = useSearchParams();
  const { t } = usePrefs();
  const [sort, setSort] = useState<Sort>("new");
  const [kind, setKind] = useState<string>("");
  const tag = params.get("tag") ?? "";
  const [data, setData] = useState<FeedDto | null>(null);
  const [stats, setStats] = useState<{ posts: number; with_evidence: number; comments: number } | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [composing, setComposing] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    try {
      setData(await api.feed({ sort, kind: kind || undefined, tag: tag || undefined, limit: 30 }));
    } catch (err) {
      setError(err instanceof ApiError ? new Error(err.message) : err);
    }
  }, [sort, kind, tag]);

  useEffect(() => {
    setData(null);
    load();
  }, [load]);

  useEffect(() => {
    api.communityStats().then(setStats).catch(() => {});
  }, []);

  function onPublished(post: PostDto) {
    setComposing(false);
    setData((current) =>
      current ? { ...current, posts: [post, ...current.posts], total: current.total + 1 } : current,
    );
  }

  return (
    <>
      <header className="page-head">
        <div className="eyebrow">{t("The commons", "مشترکہ صحن")}</div>
        <div className="row between top">
          <div>
            <h1>{t("Shared research", "مشترکہ تحقیق")}</h1>
            <p className="lede">
              {t(
                "Post a finding, ask a question, or challenge a claim. Scripture is quoted by reference so every ayah on this page comes from the database — including in the comments.",
                "کوئی نتیجہ پیش کریں، سوال پوچھیں، یا کسی دعوے کو چیلنج کریں۔ آیات حوالے سے پیش ہوتی ہیں، اس لیے اس صفحے کی ہر آیت ڈیٹا بیس سے آتی ہے۔",
              )}
            </p>
          </div>
          <button className="btn" onClick={() => setComposing((v) => !v)}>
            <Icon.note size={14} />
            {composing ? t("Close", "بند کریں") : t("Share something", "کچھ پیش کریں")}
          </button>
        </div>
      </header>

      {stats && (
        <div className="stat-grid">
          <Stat n={<CountUp value={stats.posts} />} k={t("posts", "پوسٹس")} />
          <Stat
            n={<CountUp value={stats.with_evidence} />}
            k={t("with evidence", "شواہد کے ساتھ")}
            accent
            hint={stats.posts ? `${Math.round((stats.with_evidence / stats.posts) * 100)}% of posts` : undefined}
          />
          <Stat n={<CountUp value={stats.comments} />} k={t("comments", "تبصرے")} />
        </div>
      )}

      {composing && <Composer onPublished={onPublished} onCancel={() => setComposing(false)} />}

      <div className="row between mt-4" style={{ marginBottom: "var(--s-3)" }}>
        <Segmented
          label="Feed order"
          value={sort}
          onChange={(next) => setSort(next as Sort)}
          options={[
            { value: "new", label: "New" },
            { value: "useful", label: "Most useful", hint: "By upvote — popularity, not correctness" },
            { value: "evidence", label: "With evidence", hint: "Posts attaching something checkable" },
            { value: "discussed", label: "Discussed" },
          ]}
        />
        <select
          value={kind}
          onChange={(event) => setKind(event.target.value)}
          style={{ width: "auto", minWidth: 140 }}
          aria-label="filter by post kind"
        >
          <option value="">All kinds</option>
          <option value="question">Questions</option>
          <option value="insight">Insights</option>
          <option value="finding">Findings</option>
          <option value="hypothesis">Hypotheses</option>
          <option value="correction">Corrections</option>
        </select>
      </div>

      {tag && (
        <Notice kind="info">
          Filtered to <strong>#{tag}</strong>.{" "}
          <Link href="/community">Clear the filter</Link>
        </Notice>
      )}

      <ErrorNote error={error} />

      {!data ? (
        <FeedSkeleton />
      ) : data.posts.length === 0 ? (
        <EmptyState title={t("Nothing here yet", "ابھی کچھ نہیں")} glyph="﴿﴾">
          {t(
            "Be the first. A post that attaches a hypothesis or a finding brings its evidence with it, so other researchers can check the claim rather than only agree with it.",
            "پہل کیجیے۔ جو پوسٹ کوئی مفروضہ یا نتیجہ منسلک کرتی ہے، وہ اپنے شواہد ساتھ لاتی ہے۔",
          )}
        </EmptyState>
      ) : (
        <>
          <div className="stack">
            {data.posts.map((post) => (
              <PostCard key={post.id} post={post} />
            ))}
          </div>
          <Notice kind="info">{data.note}</Notice>
        </>
      )}
    </>
  );
}

function FeedSkeleton() {
  return (
    <div className="stack" aria-busy="true">
      <SkeletonCard lines={3} />
      <SkeletonCard lines={2} />
      <SkeletonCard lines={3} />
    </div>
  );
}
