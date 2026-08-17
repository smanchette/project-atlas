import UniversalFormModesReview from "../components/UniversalFormModesReview";

export function isLoopbackThemeLabHost(hostname: string): boolean {
  const normalized = hostname.trim().toLowerCase();
  return normalized === "localhost" || normalized === "127.0.0.1" || normalized === "::1" || normalized === "[::1]";
}

export default function UniversalFormModesReviewPage() {
  const hostname = typeof window === "undefined" ? "localhost" : window.location.hostname;
  if (!isLoopbackThemeLabHost(hostname)) {
    return <main className="universalFormModesReviewDenied" role="alert"><h1>Local Theme Lab only</h1><p>This operator review is unavailable outside a loopback host.</p></main>;
  }
  return <UniversalFormModesReview />;
}
