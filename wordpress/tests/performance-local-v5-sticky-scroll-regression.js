(function installProjectAtlasV5StickyScrollRegression(global) {
  "use strict";

  var API_NAME = "ProjectAtlasV5StickyScrollRegression";
  var RESULT_SCHEMA = "project-atlas-performance-local-v5-sticky-scroll-regression@1";
  var STYLESHEET_HASH_BY_VERSION = Object.freeze({
    "0.57.11": "3a227011edb8dcd56e6a30ba701dddc488c7bb1b3c5556530c49cb4b39a4445e",
    "0.57.12": "b0834b9e8fde7dee64d645fe831a8e862736006a15b21b0e7cf8b14e15fe49e3",
  });
  var AUTORUN_ATTRIBUTE = "data-atlas-v5-sticky-proof-result";
  var AUTORUN_PARAMETERS = Object.freeze({
    marker: "atlas-sticky-proof",
    version: "atlas-sticky-version",
    session: "atlas-sticky-session",
    secondary: "atlas-sticky-secondary",
  });
  var SUPPORTED_VERSIONS = ["0.57.11", "0.57.12"];
  var VIEWPORTS = [
    { width: 1440, height: 1000 },
    { width: 1280, height: 800 },
    { width: 768, height: 1024 },
    { width: 390, height: 844 },
    { width: 360, height: 800 },
  ];
  var SELECTORS = {
    root: "[data-project-atlas-v5-root]",
    stack: "[data-v5-top-conversion-stack]",
    phone: ".performanceLocalV5StickyPhoneBar",
    action: ".performanceLocalV5StickyActionBanner",
    oldBottomStack: ".performanceLocalV5StickyActions, .performanceLocalStickyActions",
    firstContent: ".performanceLocalSite, .performanceLocalV5Header",
  };
  var TOLERANCE = 2;

  function round(value) {
    return Math.round(value * 100) / 100;
  }

  function rect(element) {
    var value = element.getBoundingClientRect();
    return {
      top: round(value.top),
      right: round(value.right),
      bottom: round(value.bottom),
      left: round(value.left),
      width: round(value.width),
      height: round(value.height),
    };
  }

  function approximately(actual, expected) {
    return Math.abs(actual - expected) <= TOLERANCE;
  }

  function isVisible(element) {
    var style = global.getComputedStyle(element);
    var value = element.getBoundingClientRect();
    return style.display !== "none"
      && style.visibility === "visible"
      && Number(style.opacity) > 0
      && value.width > 0
      && value.height > 0
      && value.bottom > 0
      && value.top < global.innerHeight;
  }

  function exactOne(selector) {
    var matches = Array.from(document.querySelectorAll(selector));
    return { matches: matches, element: matches.length === 1 ? matches[0] : null };
  }

  function renderedBridgeVersions() {
    var versions = [];
    var walker = document.createTreeWalker(document, NodeFilter.SHOW_COMMENT);
    var node;
    while ((node = walker.nextNode())) {
      var match = node.nodeValue.match(/^\s*Project Atlas Metadata Bridge v(0\.57\.\d+)\s*$/);
      if (match) versions.push(match[1]);
    }
    return versions;
  }

  function renderedBridgeIdentity() {
    var links = Array.from(document.querySelectorAll("#project-atlas-performance-local-v5-css"));
    var comments = renderedBridgeVersions();
    if (links.length !== 1) {
      return { links: links.length, comments: comments, version: null, stylesheet: null };
    }
    var link = links[0];
    var href = new URL(link.href, global.location.href);
    var versions = href.searchParams.getAll("ver");
    var parameterNames = Array.from(href.searchParams.keys());
    var stylesheetHash = versions.length === 1 ? versions[0] : null;
    var version = null;
    Object.keys(STYLESHEET_HASH_BY_VERSION).forEach(function matchHash(candidate) {
      if (STYLESHEET_HASH_BY_VERSION[candidate] === stylesheetHash) version = candidate;
    });
    var exactStylesheet = link.relList.contains("stylesheet")
      && href.origin === global.location.origin
      && href.pathname.endsWith("/assets/performance-local-v5.css")
      && href.hash === ""
      && parameterNames.length === 1
      && parameterNames[0] === "ver"
      && version !== null;
    var commentsConsistent = comments.every(function commentMatches(value) {
      return value === version;
    });
    return {
      links: links.length,
      comments: comments,
      comments_consistent: commentsConsistent,
      exact_stylesheet: exactStylesheet,
      stylesheet: href.origin + href.pathname + href.search,
      stylesheet_sha256: stylesheetHash,
      version: exactStylesheet && commentsConsistent ? version : null,
    };
  }

  function initialAdminOffset(session) {
    if (session === "logged_out") return 0;
    return global.innerWidth <= 782 ? 46 : 32;
  }

  function currentAdminOffset(session) {
    if (session === "logged_out") return 0;
    var adminBar = document.querySelector("#wpadminbar");
    if (!adminBar) return 0;
    return round(Math.max(0, adminBar.getBoundingClientRect().bottom));
  }

  function add(assertions, phase, code, pass, details) {
    assertions.push({
      phase: phase,
      code: phase + "." + code,
      pass: Boolean(pass),
      details: details,
    });
  }

  function hitIsWithin(element) {
    var value = element.getBoundingClientRect();
    var x = Math.max(0, Math.min(global.innerWidth - 1, value.left + value.width / 2));
    var y = Math.max(0, Math.min(global.innerHeight - 1, value.top + value.height / 2));
    var hit = document.elementFromPoint(x, y);
    return hit !== null && (hit === element || element.contains(hit));
  }

  function measurePhase(phase, options, assertions) {
    var rootResult = exactOne(SELECTORS.root);
    var stackResult = exactOne(SELECTORS.stack);
    var phoneResult = exactOne(SELECTORS.phone);
    var actions = Array.from(document.querySelectorAll(SELECTORS.action));
    var oldBottomStacks = Array.from(document.querySelectorAll(SELECTORS.oldBottomStack));

    add(assertions, phase, "one_root", rootResult.matches.length === 1, {
      actual: rootResult.matches.length,
      expected: 1,
    });
    add(assertions, phase, "one_stack", stackResult.matches.length === 1, {
      actual: stackResult.matches.length,
      expected: 1,
    });
    add(assertions, phase, "one_phone_row", phoneResult.matches.length === 1, {
      actual: phoneResult.matches.length,
      expected: 1,
    });
    add(assertions, phase, "secondary_row_count", actions.length === (options.secondaryActionEnabled ? 1 : 0), {
      actual: actions.length,
      expected: options.secondaryActionEnabled ? 1 : 0,
    });
    add(assertions, phase, "no_bottom_conversion_stack", oldBottomStacks.length === 0, {
      actual: oldBottomStacks.length,
      expected: 0,
    });

    if (!rootResult.element || !stackResult.element || !phoneResult.element
        || actions.length !== (options.secondaryActionEnabled ? 1 : 0)) {
      return null;
    }

    var root = rootResult.element;
    var stack = stackResult.element;
    var phone = phoneResult.element;
    var action = actions.length === 1 ? actions[0] : null;
    var rootRect = rect(root);
    var stackRect = rect(stack);
    var phoneRect = rect(phone);
    var actionRect = action ? rect(action) : null;
    var phoneLinks = Array.from(phone.querySelectorAll("a[href^='tel:']"));
    var actionLinks = action ? Array.from(action.querySelectorAll("a[href]")) : [];
    var stackStyle = global.getComputedStyle(stack);
    var rootStyle = global.getComputedStyle(root);
    var phaseAdminBars = Array.from(document.querySelectorAll("#wpadminbar"));
    var phaseAdminRect = phaseAdminBars.length === 1 ? rect(phaseAdminBars[0]) : null;
    var scrollingElement = document.scrollingElement || document.documentElement;
    var viewportWidth = document.documentElement.clientWidth;
    var documentWidth = Math.max(
      document.documentElement.scrollWidth,
      document.body ? document.body.scrollWidth : 0,
      scrollingElement.scrollWidth
    );
    var expectedTop = currentAdminOffset(options.session);
    var expectedStackHeight = phoneRect.height + (actionRect ? actionRect.height : 0);
    var enabledAttribute = stack.getAttribute("data-v5-top-action-enabled");
    var rootEnabledAttribute = root.getAttribute("data-v5-top-action-enabled");
    var firstContent = root.querySelector(SELECTORS.firstContent);
    var firstContentRect = firstContent ? rect(firstContent) : null;

    add(assertions, phase, "admin_bar_count", phaseAdminBars.length === (options.session === "logged_in" ? 1 : 0), {
      actual: phaseAdminBars.length,
      expected: options.session === "logged_in" ? 1 : 0,
      rect: phaseAdminRect,
    });

    add(assertions, phase, "stack_admin_offset", approximately(stackRect.top, expectedTop), {
      actual: stackRect.top,
      expected: expectedTop,
      viewport_width: global.innerWidth,
      session: options.session,
    });
    add(assertions, phase, "stack_visible", isVisible(stack), {
      rect: stackRect,
      position: stackStyle.position,
    });
    add(assertions, phase, "stack_spans_viewport", approximately(stackRect.left, 0)
      && approximately(stackRect.right, viewportWidth), {
      rect: stackRect,
      viewport_width: viewportWidth,
    });
    add(assertions, phase, "phone_visible", isVisible(phone), { rect: phoneRect });
    add(assertions, phase, "phone_first", approximately(phoneRect.top, stackRect.top), {
      phone_top: phoneRect.top,
      stack_top: stackRect.top,
    });
    add(assertions, phase, "one_phone_link", phoneLinks.length === 1, {
      actual: phoneLinks.length,
      expected: 1,
    });
    add(assertions, phase, "phone_hit_test", phoneLinks.length === 1 && hitIsWithin(phoneLinks[0]), {
      rect: phoneRect,
    });
    add(assertions, phase, "stack_height_matches_rows", approximately(stackRect.height, expectedStackHeight), {
      stack_height: stackRect.height,
      row_height_total: round(expectedStackHeight),
    });
    add(assertions, phase, "document_has_no_horizontal_overflow", documentWidth <= viewportWidth + TOLERANCE, {
      document_width: documentWidth,
      viewport_width: viewportWidth,
    });
    add(assertions, phase, "root_has_no_horizontal_overflow", root.scrollWidth <= root.clientWidth + TOLERANCE, {
      scroll_width: root.scrollWidth,
      client_width: root.clientWidth,
    });

    if (options.secondaryActionEnabled && action && actionRect) {
      add(assertions, phase, "secondary_enabled_attribute", enabledAttribute === "true"
        && rootEnabledAttribute === "true", {
        stack: enabledAttribute,
        root: rootEnabledAttribute,
      });
      add(assertions, phase, "secondary_visible", isVisible(action), { rect: actionRect });
      add(assertions, phase, "one_secondary_link", actionLinks.length === 1, {
        actual: actionLinks.length,
        expected: 1,
      });
      add(assertions, phase, "secondary_follows_phone", approximately(actionRect.top, phoneRect.bottom), {
        action_top: actionRect.top,
        phone_bottom: phoneRect.bottom,
      });
      add(assertions, phase, "secondary_ends_stack", approximately(actionRect.bottom, stackRect.bottom), {
        action_bottom: actionRect.bottom,
        stack_bottom: stackRect.bottom,
      });
      add(assertions, phase, "secondary_hit_test", actionLinks.length === 1 && hitIsWithin(actionLinks[0]), {
        rect: actionRect,
      });
    } else if (!options.secondaryActionEnabled) {
      var configuredActionHeight = parseFloat(rootStyle.getPropertyValue("--plv5-city-action-height"));
      add(assertions, phase, "secondary_disabled_attribute", enabledAttribute === "false"
        && rootEnabledAttribute === "false", {
        stack: enabledAttribute,
        root: rootEnabledAttribute,
      });
      add(assertions, phase, "secondary_disabled_height_zero", configuredActionHeight === 0, {
        css_custom_property: rootStyle.getPropertyValue("--plv5-city-action-height").trim(),
      });
      add(assertions, phase, "secondary_disabled_no_reserved_row", approximately(stackRect.height, phoneRect.height), {
        stack_height: stackRect.height,
        phone_height: phoneRect.height,
      });
    }

    if (phase === "initial") {
      add(assertions, phase, "first_content_present", Boolean(firstContentRect), {
        selector: SELECTORS.firstContent,
      });
      if (firstContentRect) {
        add(assertions, phase, "no_gap_after_stack", approximately(firstContentRect.top, stackRect.bottom), {
          first_content_top: firstContentRect.top,
          stack_bottom: stackRect.bottom,
        });
      }
    }

    return {
      scroll_y: round(global.scrollY),
      root: rootRect,
      stack: stackRect,
      phone: phoneRect,
      action: actionRect,
      expected_stack_top: expectedTop,
      admin_bar: phaseAdminRect,
      admin_bar_position: phaseAdminBars.length === 1
        ? global.getComputedStyle(phaseAdminBars[0]).position
        : null,
      position: stackStyle.position,
      document_width: documentWidth,
      document_height: Math.max(
        document.documentElement.scrollHeight,
        document.body ? document.body.scrollHeight : 0,
        scrollingElement.scrollHeight
      ),
    };
  }

  function afterAnimationFrames(count) {
    return new Promise(function resolveAfterFrames(resolve) {
      function next() {
        if (count-- <= 0) {
          resolve();
          return;
        }
        global.requestAnimationFrame(next);
      }
      next();
    });
  }

  function validateOptions(options) {
    if (!options || typeof options !== "object") throw new Error("Options are required.");
    if (SUPPORTED_VERSIONS.indexOf(options.bridgeVersion) === -1) {
      throw new Error("bridgeVersion must be exactly 0.57.11 or 0.57.12.");
    }
    if (options.session !== "logged_out" && options.session !== "logged_in") {
      throw new Error("session must be exactly logged_out or logged_in.");
    }
    if (typeof options.expectedUrl !== "string" || options.expectedUrl.length === 0) {
      throw new Error("expectedUrl is required.");
    }
    if (typeof options.secondaryActionEnabled !== "boolean") {
      throw new Error("secondaryActionEnabled must be a boolean.");
    }
    if (options.restoreScroll !== undefined && typeof options.restoreScroll !== "boolean") {
      throw new Error("restoreScroll must be a boolean when supplied.");
    }
  }

  function matrix(secondaryActionEnabled) {
    var expectedSecondaryAction = secondaryActionEnabled !== false;
    var cases = [];
    SUPPORTED_VERSIONS.forEach(function addVersion(bridgeVersion) {
      ["logged_out", "logged_in"].forEach(function addSession(session) {
        VIEWPORTS.forEach(function addViewport(viewport) {
          cases.push({
            bridgeVersion: bridgeVersion,
            session: session,
            width: viewport.width,
            height: viewport.height,
            secondaryActionEnabled: expectedSecondaryAction,
            expectedStatus: bridgeVersion === "0.57.11" && session === "logged_in"
              && viewport.width > 600
              ? "EXPECTED_FAILURE_CONFIRMED"
              : "PASS",
          });
        });
      });
    });
    return cases;
  }

  async function run(options) {
    validateOptions(options);
    var expectedUrl = new URL(options.expectedUrl);
    var actualUrl = new URL(global.location.href);
    var assertions = [];
    var originalScrollY = global.scrollY;
    var viewportSupported = VIEWPORTS.some(function sameViewport(viewport) {
      return viewport.width === global.innerWidth && viewport.height === global.innerHeight;
    });
    var loggedIn = document.body.classList.contains("logged-in")
      && document.body.classList.contains("admin-bar");
    var adminBars = Array.from(document.querySelectorAll("#wpadminbar"));
    var bridgeIdentity = renderedBridgeIdentity();

    add(assertions, "preflight", "exact_url", actualUrl.origin === expectedUrl.origin
      && actualUrl.pathname === expectedUrl.pathname
      && actualUrl.search === expectedUrl.search, {
      actual: actualUrl.origin + actualUrl.pathname + actualUrl.search,
      expected: expectedUrl.origin + expectedUrl.pathname + expectedUrl.search,
    });
    add(assertions, "preflight", "supported_viewport", viewportSupported, {
      actual: { width: global.innerWidth, height: global.innerHeight },
      supported: VIEWPORTS,
    });
    add(assertions, "preflight", "document_ready", document.readyState === "complete", {
      actual: document.readyState,
      expected: "complete",
    });
    add(assertions, "preflight", "wordpress_page_8", document.body.classList.contains("page-id-8"), {
      required_body_class: "page-id-8",
    });
    var pageRoots = Array.from(document.querySelectorAll(SELECTORS.root));
    add(assertions, "preflight", "city_service_surface", pageRoots.length === 1
      && pageRoots[0].getAttribute("data-v5-surface") === "city_service", {
      root_count: pageRoots.length,
      surface: pageRoots.length === 1 ? pageRoots[0].getAttribute("data-v5-surface") : null,
    });
    add(assertions, "preflight", "device_pixel_ratio_is_finite", Number.isFinite(global.devicePixelRatio)
      && global.devicePixelRatio > 0, { actual: global.devicePixelRatio });
    add(assertions, "preflight", "exact_rendered_bridge_version", bridgeIdentity.version === options.bridgeVersion, {
      actual: bridgeIdentity,
      expected_version: options.bridgeVersion,
      expected_stylesheet_sha256: STYLESHEET_HASH_BY_VERSION[options.bridgeVersion],
    });
    add(assertions, "preflight", "session_matches", loggedIn === (options.session === "logged_in"), {
      actual: loggedIn ? "logged_in" : "logged_out",
      expected: options.session,
    });
    add(assertions, "preflight", "admin_bar_count", adminBars.length === (options.session === "logged_in" ? 1 : 0), {
      actual: adminBars.length,
      expected: options.session === "logged_in" ? 1 : 0,
    });

    try {
      global.scrollTo(0, 0);
      await afterAnimationFrames(3);
      add(assertions, "initial", "document_at_top", global.scrollY === 0, { actual: global.scrollY });

      if (options.session === "logged_in" && adminBars.length === 1) {
        var adminRect = rect(adminBars[0]);
        add(assertions, "initial", "admin_bar_visible", isVisible(adminBars[0]), { rect: adminRect });
        add(assertions, "initial", "admin_bar_exact_height", approximately(adminRect.top, 0)
          && approximately(adminRect.bottom, initialAdminOffset(options.session)), {
          rect: adminRect,
          expected_bottom: initialAdminOffset(options.session),
        });
      }

      var initial = measurePhase("initial", options, assertions);
      var scrollingElement = document.scrollingElement || document.documentElement;
      var maximumScroll = Math.max(0, scrollingElement.scrollHeight - global.innerHeight);
      var targetScroll = Math.min(maximumScroll, Math.max(240, Math.round(global.innerHeight * 0.75)));
      add(assertions, "preflight", "document_is_scrollable", maximumScroll >= 240, {
        maximum_scroll: maximumScroll,
        required: 240,
      });

      global.scrollTo({ top: targetScroll, left: 0, behavior: "instant" });
      await afterAnimationFrames(5);
      var actualScroll = global.scrollY;
      add(assertions, "scrolled", "real_window_scroll", actualScroll >= 240
        && approximately(scrollingElement.scrollTop, actualScroll), {
        target_scroll_y: targetScroll,
        window_scroll_y: actualScroll,
        scrolling_element_scroll_top: scrollingElement.scrollTop,
      });
      var scrolled = measurePhase("scrolled", options, assertions);
      if (initial && scrolled) {
        var rootTravel = initial.root.top - scrolled.root.top;
        add(assertions, "scrolled", "document_root_moved_with_scroll", approximately(rootTravel, actualScroll), {
          root_travel: round(rootTravel),
          scroll_y: round(actualScroll),
        });
      }

      var failures = assertions.filter(function failed(assertion) { return !assertion.pass; });
      var expectedKnownFailure = options.bridgeVersion === "0.57.11"
        && options.session === "logged_in"
        && global.innerWidth > 600;
      var knownFailureCodes = [
        "scrolled.stack_admin_offset",
        "scrolled.phone_hit_test",
      ];
      var knownFailureOnly = failures.some(function isOffsetFailure(assertion) {
        return assertion.code === "scrolled.stack_admin_offset";
      }) && failures.every(function isKnown05711Failure(assertion) {
        return knownFailureCodes.indexOf(assertion.code) !== -1;
      });
      var status;
      if (expectedKnownFailure) {
        status = knownFailureOnly ? "EXPECTED_FAILURE_CONFIRMED" : "FAIL";
        if (failures.length === 0) {
          add(assertions, "result", "known_05711_failure_not_reproduced", false, {
            expected_failure: "scrolled.stack_admin_offset",
          });
          failures = assertions.filter(function failed(assertion) { return !assertion.pass; });
          status = "FAIL";
        }
      } else {
        status = failures.length === 0 ? "PASS" : "FAIL";
      }

      return {
        result_schema: RESULT_SCHEMA,
        status: status,
        expected_status: expectedKnownFailure ? "EXPECTED_FAILURE_CONFIRMED" : "PASS",
        bridge_version: options.bridgeVersion,
        session: options.session,
        page: actualUrl.origin + actualUrl.pathname + actualUrl.search,
        viewport: {
          width: global.innerWidth,
          height: global.innerHeight,
          device_pixel_ratio: global.devicePixelRatio,
        },
        secondary_action_enabled: options.secondaryActionEnabled,
        actual_document_scroll: Boolean(scrolled && scrolled.scroll_y > 0),
        initial: initial,
        scrolled: scrolled,
        assertion_count: assertions.length,
        failures: failures,
        assertions: assertions,
      };
    } finally {
      if (options.restoreScroll !== false) {
        global.scrollTo({ top: originalScrollY, left: 0, behavior: "instant" });
        await afterAnimationFrames(2);
      }
    }
  }

  function exactParameter(parameters, name) {
    var values = parameters.getAll(name);
    if (values.length !== 1) throw new Error(name + " must occur exactly once.");
    return values[0];
  }

  function applySecondaryDisabledAutorunFixture() {
    var roots = Array.from(document.querySelectorAll(SELECTORS.root));
    var stacks = Array.from(document.querySelectorAll(SELECTORS.stack));
    var phones = Array.from(document.querySelectorAll(SELECTORS.phone));
    var actions = Array.from(document.querySelectorAll(SELECTORS.action));
    if (roots.length !== 1 || stacks.length !== 1 || phones.length !== 1 || actions.length !== 1) {
      throw new Error("Secondary-disabled fixture requires one enabled root, stack, phone, and action.");
    }
    var root = roots[0];
    var stack = stacks[0];
    var phone = phones[0];
    var action = actions[0];
    if (!root.contains(stack) || !stack.contains(phone) || action.parentElement !== stack
        || root.getAttribute("data-v5-top-action-enabled") !== "true"
        || stack.getAttribute("data-v5-top-action-enabled") !== "true"
        || root.hasAttribute("data-atlas-v5-sticky-proof-fixture")) {
      throw new Error("Secondary-disabled fixture opening identity differs.");
    }
    var identity = {
      fixture: "secondary-disabled",
      projection: "enabled-rendered-dom-to-disabled-css-state",
      original: {
        root_count: roots.length,
        stack_count: stacks.length,
        phone_count: phones.length,
        action_count: actions.length,
        root_action_enabled: "true",
        stack_action_enabled: "true",
        stack_action_mode: stack.getAttribute("data-v5-top-action-mode"),
      },
      projected: {
        action_removed: true,
        root_action_enabled: "false",
        stack_action_enabled: "false",
        root_marker: "secondary-disabled",
      },
      metadata_writes: 0,
    };
    action.remove();
    root.setAttribute("data-v5-top-action-enabled", "false");
    stack.setAttribute("data-v5-top-action-enabled", "false");
    root.setAttribute("data-atlas-v5-sticky-proof-fixture", "secondary-disabled");
    return identity;
  }

  function scheduleQueryAutorun() {
    var parameters = new URLSearchParams(global.location.search);
    var markers = parameters.getAll(AUTORUN_PARAMETERS.marker);
    if (markers.length !== 1 || markers[0] !== "1") return;

    async function autorun() {
      document.documentElement.setAttribute(AUTORUN_ATTRIBUTE, "RUNNING");
      try {
        var secondary = exactParameter(parameters, AUTORUN_PARAMETERS.secondary);
        if (secondary !== "true" && secondary !== "false") {
          throw new Error(AUTORUN_PARAMETERS.secondary + " must be exactly true or false.");
        }
        var runOptions = {
          bridgeVersion: exactParameter(parameters, AUTORUN_PARAMETERS.version),
          session: exactParameter(parameters, AUTORUN_PARAMETERS.session),
          secondaryActionEnabled: secondary === "true",
          expectedUrl: global.location.href,
          restoreScroll: false,
        };
        validateOptions(runOptions);
        var fixtureIdentity = secondary === "false"
          ? applySecondaryDisabledAutorunFixture()
          : null;
        var result = await run(runOptions);
        result.fixture_identity = fixtureIdentity;
        document.documentElement.setAttribute(AUTORUN_ATTRIBUTE, JSON.stringify(result));
      } catch (error) {
        document.documentElement.setAttribute(AUTORUN_ATTRIBUTE, "ERROR");
        if (global.console && typeof global.console.error === "function") {
          global.console.error("Project Atlas V5 sticky proof failed.", error);
        }
      }
    }

    if (document.readyState === "complete") {
      global.setTimeout(autorun, 0);
    } else {
      global.addEventListener("load", autorun, { once: true });
    }
  }

  if (Object.prototype.hasOwnProperty.call(global, API_NAME)) {
    if (global[API_NAME] && global[API_NAME].resultSchema === RESULT_SCHEMA) return;
    throw new Error(API_NAME + " is already installed with a different contract.");
  }

  Object.defineProperty(global, API_NAME, {
    configurable: false,
    enumerable: false,
    writable: false,
    value: Object.freeze({
      resultSchema: RESULT_SCHEMA,
      supportedVersions: Object.freeze(SUPPORTED_VERSIONS.slice()),
      autorunAttribute: AUTORUN_ATTRIBUTE,
      autorunParameters: AUTORUN_PARAMETERS,
      viewports: Object.freeze(VIEWPORTS.map(function copyViewport(viewport) {
        return Object.freeze({ width: viewport.width, height: viewport.height });
      })),
      matrix: matrix,
      run: run,
    }),
  });
  scheduleQueryAutorun();
})(window);
