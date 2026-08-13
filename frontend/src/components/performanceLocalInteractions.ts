export type PerformanceLocalStickyVisibilityInput = Readonly<{
  actionsAvailable: boolean;
  formFocusRisk: boolean;
  heroConversionVisible: boolean;
  mobileMenuOpen: boolean;
  mobileViewport: boolean;
}>;

export type PerformanceLocalStickyVisibilityReason =
  | "shown_after_hero"
  | "hidden_no_actions"
  | "hidden_non_mobile"
  | "hidden_menu_open"
  | "hidden_form_focus"
  | "hidden_hero_actions_visible";

export type PerformanceLocalStickyVisibility = Readonly<{
  reason: PerformanceLocalStickyVisibilityReason;
  visible: boolean;
}>;

/**
 * One deterministic policy owns the mobile conversion layer. The ordering is
 * intentional: a missing action or the wrong breakpoint prevents a wrapper,
 * while modal navigation and focused form controls take precedence over the
 * hero-intersection signal.
 */
export function resolvePerformanceLocalStickyVisibility(
  input: PerformanceLocalStickyVisibilityInput,
): PerformanceLocalStickyVisibility {
  if (!input.actionsAvailable) {
    return { visible: false, reason: "hidden_no_actions" };
  }
  if (!input.mobileViewport) {
    return { visible: false, reason: "hidden_non_mobile" };
  }
  if (input.mobileMenuOpen) {
    return { visible: false, reason: "hidden_menu_open" };
  }
  if (input.formFocusRisk) {
    return { visible: false, reason: "hidden_form_focus" };
  }
  if (input.heroConversionVisible) {
    return { visible: false, reason: "hidden_hero_actions_visible" };
  }
  return { visible: true, reason: "shown_after_hero" };
}
