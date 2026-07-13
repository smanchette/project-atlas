import {
  Building2,
  BookOpenText,
  ClipboardCheck,
  DatabaseBackup,
  FileSearch,
  FileCode2,
  Images,
  FileText,
  Home,
  ListTodo,
  ListChecks,
  Map,
  MapPin,
  Plug,
  ShieldCheck,
  Settings,
  Wrench
} from "lucide-react";
import { NavLink, Route, Routes } from "react-router-dom";

import Dashboard from "./pages/Dashboard";
import BackupsPage from "./pages/BackupsPage";
import ApprovalQueuePage from "./pages/ApprovalQueuePage";
import CitiesPage from "./pages/CitiesPage";
import GeneratedPagesPage from "./pages/GeneratedPagesPage";
import GeneratedPagePreview from "./pages/GeneratedPagePreview";
import ExportPackagePage from "./pages/ExportPackagePage";
import KnowledgeBlocksPage from "./pages/KnowledgeBlocksPage";
import MediaLibraryPage from "./pages/MediaLibraryPage";
import ModulePage from "./pages/ModulePage";
import WordPressDraftReviewPage from "./pages/WordPressDraftReviewPage";
import WordPressDraftQualityReviewPage from "./pages/WordPressDraftQualityReviewPage";
import WordPressDraftQueuePage from "./pages/WordPressDraftQueuePage";
import WordPressSandboxPage from "./pages/WordPressSandboxPage";
import WordPressDraftUpdateSandboxPage from "./pages/WordPressDraftUpdateSandboxPage";
import WordPressPublishSafetySandboxPage from "./pages/WordPressPublishSafetySandboxPage";
import WordPressMediaSafetyPage from "./pages/WordPressMediaSafetyPage";
import WordPressMetadataSafetyPage from "./pages/WordPressMetadataSafetyPage";
import type { Business, City, County, FieldConfig, GeneratedPage, Service } from "./types";

const navItems = [
  { to: "/", label: "Dashboard", icon: Home },
  { to: "/businesses", label: "Business Profile", icon: Building2 },
  { to: "/services", label: "Services", icon: Wrench },
  { to: "/knowledge-blocks", label: "Knowledge Blocks", icon: BookOpenText },
  { to: "/counties", label: "Counties", icon: Map },
  { to: "/cities", label: "Cities", icon: MapPin },
  { to: "/generated-pages", label: "Generated Pages", icon: FileText },
  { to: "/approval-queue", label: "Approval Queue", icon: ClipboardCheck },
  { to: "/image-metadata", label: "Media Library", icon: Images },
  { to: "/backups", label: "Backups", icon: DatabaseBackup },
  { to: "/wordpress-sandbox", label: "WordPress Sandbox", icon: Plug },
  { to: "/wordpress-draft-queue", label: "WP Draft Queue", icon: ListChecks },
  { to: "/wordpress-draft-review", label: "WP Draft Review", icon: FileSearch },
  { to: "/wordpress-draft-update", label: "WP Draft Update", icon: ClipboardCheck },
  { to: "/wordpress-publish-safety", label: "WP Publish Safety", icon: ShieldCheck },
  { to: "/wordpress-media-safety", label: "WP Media Safety", icon: Images },
  { to: "/wordpress-metadata-safety", label: "WP Metadata Safety", icon: FileCode2 },
  { to: "/wordpress-quality-review", label: "WP Quality Review", icon: ListTodo },
  { to: "/settings", label: "Settings", icon: Settings }
];

const businessFields: FieldConfig<Business>[] = [
  { key: "company_name", label: "Company Name", required: true },
  { key: "brand_name", label: "Brand Name" },
  { key: "business_type", label: "Business Type", required: true },
  { key: "phone", label: "Phone" },
  { key: "email", label: "Email", type: "email" },
  { key: "website", label: "Website", type: "url" },
  { key: "main_city", label: "Main City" },
  { key: "state", label: "State", required: true },
  { key: "license_number", label: "License Number" },
  { key: "certified_operator", label: "Certified Operator" },
  { key: "description", label: "Description", type: "textarea" }
];

const serviceFields: FieldConfig<Service>[] = [
  { key: "business_id", label: "Business ID", type: "number", required: true },
  { key: "service_name", label: "Service Name", required: true },
  { key: "service_slug", label: "Service Slug", required: true },
  { key: "service_category", label: "Service Category" },
  { key: "short_description", label: "Short Description", type: "textarea" },
  { key: "long_description", label: "Long Description", type: "textarea" },
  { key: "status", label: "Status", required: true }
];

const countyFields: FieldConfig<County>[] = [
  { key: "state", label: "State", required: true },
  { key: "county_name", label: "County Name", required: true },
  { key: "status", label: "Status", required: true }
];

const cityFields: FieldConfig<City>[] = [
  { key: "county_id", label: "County ID", type: "number", required: true },
  { key: "city_name", label: "City Name", required: true },
  { key: "state", label: "State", required: true },
  { key: "city_slug", label: "City Slug", required: true },
  { key: "status", label: "Status", required: true }
];

const pageFields: FieldConfig<GeneratedPage>[] = [
  { key: "business_id", label: "Business ID", type: "number", required: true },
  { key: "service_id", label: "Service ID", type: "number", required: true },
  { key: "city_id", label: "City ID", type: "number" },
  { key: "county_id", label: "County ID", type: "number" },
  { key: "page_type", label: "Page Type", required: true },
  { key: "page_title", label: "Page Title", required: true },
  { key: "page_slug", label: "Page Slug", required: true },
  { key: "meta_title", label: "Meta Title" },
  { key: "meta_description", label: "Meta Description", type: "textarea" },
  { key: "h1", label: "H1" },
  { key: "content_body", label: "Content Body", type: "textarea" },
  { key: "status", label: "Status", required: true },
  { key: "wordpress_url", label: "WordPress URL", type: "url" }
];

function App() {
  return (
    <Routes>
      <Route path="/generated-pages/:id/preview" element={<GeneratedPagePreview />} />
      <Route path="*" element={<DashboardShell />} />
    </Routes>
  );
}

function DashboardShell() {
  return (
    <div className="appShell">
      <aside className="sidebar">
        <div className="brandBlock">
          <span className="brandMark">A</span>
          <div>
            <strong>Project Atlas</strong>
            <span>Local SEO platform</span>
          </div>
        </div>
        <nav aria-label="Primary navigation">
          {navItems.map(({ to, label, icon: Icon }) => (
            <NavLink key={to} to={to} className={({ isActive }) => (isActive ? "navLink active" : "navLink")} end={to === "/"}>
              <Icon size={18} aria-hidden="true" />
              <span>{label}</span>
            </NavLink>
          ))}
        </nav>
      </aside>

      <main className="content">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route
            path="/businesses"
            element={
              <ModulePage<Business>
                title="Business Profile"
                endpoint="/api/businesses"
                fields={businessFields}
                tableColumns={["id", "company_name", "brand_name", "main_city", "state", "phone"]}
              />
            }
          />
          <Route
            path="/services"
            element={
              <ModulePage<Service>
                title="Services"
                endpoint="/api/services"
                fields={serviceFields}
                tableColumns={["id", "service_name", "service_slug", "service_category", "status"]}
              />
            }
          />
          <Route path="/knowledge-blocks" element={<KnowledgeBlocksPage />} />
          <Route
            path="/counties"
            element={
              <ModulePage<County>
                title="Counties"
                endpoint="/api/counties"
                fields={countyFields}
                tableColumns={["id", "county_name", "state", "status"]}
              />
            }
          />
          <Route
            path="/cities"
            element={<CitiesPage />}
          />
          <Route path="/generated-pages" element={<GeneratedPagesPage />} />
          <Route path="/generated-pages/:id/export" element={<ExportPackagePage />} />
          <Route path="/approval-queue" element={<ApprovalQueuePage />} />
          <Route path="/image-metadata" element={<MediaLibraryPage />} />
          <Route path="/backups" element={<BackupsPage />} />
          <Route path="/wordpress-sandbox" element={<WordPressSandboxPage />} />
          <Route path="/wordpress-draft-queue" element={<WordPressDraftQueuePage />} />
          <Route path="/wordpress-draft-review" element={<WordPressDraftReviewPage />} />
          <Route path="/wordpress-draft-update" element={<WordPressDraftUpdateSandboxPage />} />
          <Route path="/wordpress-publish-safety" element={<WordPressPublishSafetySandboxPage />} />
          <Route path="/wordpress-media-safety" element={<WordPressMediaSafetyPage />} />
          <Route path="/wordpress-metadata-safety" element={<WordPressMetadataSafetyPage />} />
          <Route path="/wordpress-quality-review" element={<WordPressDraftQualityReviewPage />} />
          <Route
            path="/settings"
            element={
              <ModulePage
                title="Settings"
                endpoint="/api/settings"
                fields={[
                  { key: "setting_key", label: "Setting Key", required: true },
                  { key: "setting_value", label: "Setting Value" },
                  { key: "description", label: "Description", type: "textarea" }
                ]}
                tableColumns={["id", "setting_key", "setting_value", "description"]}
              />
            }
          />
        </Routes>
      </main>
    </div>
  );
}

export default App;
