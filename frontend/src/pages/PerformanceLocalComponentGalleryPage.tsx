import { Link } from "react-router-dom";

import PerformanceLocalComponentGallery from "../components/PerformanceLocalComponentGallery";
import { performanceLocalActivationReadiness } from "../components/performanceLocalReadiness";
import { PERFORMANCE_LOCAL_THEME } from "../components/performanceLocalTheme";

export function PerformanceLocalComponentGalleryPage() {
  const readiness = performanceLocalActivationReadiness({
    previewImplementationPresent: true,
    observedThemeFamilyVersion: PERFORMANCE_LOCAL_THEME.version,
  });

  return (
    <main className="performanceLocalGalleryPage" data-local-operator-preview="true">
      <header className="pageHeader">
        <div>
          <span className="eyebrow">Local operator preview only</span>
          <h1>Performance Local component gallery</h1>
          <p>No Atlas persistence, production activation, provider request, publication, or deployment.</p>
          <Link className="secondaryButton" to="/generated-pages">Back to Generated Pages</Link>
        </div>
      </header>
      <PerformanceLocalComponentGallery />
      <section aria-labelledby="performance-local-readiness-title" className="panel">
        <h2 id="performance-local-readiness-title">Activation readiness</h2>
        <p role="status">
          <strong>Blocked — Performance Local is not activated and is not production-ready.</strong>
        </p>
        <dl className="detailGrid">
          <div><dt>Theme</dt><dd>{readiness.themeKey} v{readiness.themeFamilyVersion}</dd></div>
          <div><dt>Lifecycle</dt><dd>{readiness.lifecycle}</dd></div>
          <div><dt>Production ready</dt><dd>No</dd></div>
          <div><dt>Incomplete gates</dt><dd>{readiness.incompleteCount}</dd></div>
        </dl>
        <ul className="performanceLocalReadinessList">
          {readiness.items.map((item) => (
            <li data-readiness-status={item.status} key={item.key}>
              <strong>{item.label}: incomplete</strong>
              <span>{item.reason}</span>
            </li>
          ))}
        </ul>
        <p>Diagnostic only: this panel cannot activate, persist, publish, or deploy anything.</p>
      </section>
    </main>
  );
}

export default PerformanceLocalComponentGalleryPage;
