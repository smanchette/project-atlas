(function installProjectAtlasV5TypographyRegression(global) {
  "use strict";

  var API_NAME = "ProjectAtlasV5TypographyRegression";
  var RESULT_SCHEMA = "project-atlas-performance-local-v5-typography-regression@1";
  var AUTORUN_ATTRIBUTE = "data-atlas-v5-typography-proof-result";
  var STYLESHEET_HASH_BY_VERSION = Object.freeze({
    "0.57.12": "b0834b9e8fde7dee64d645fe831a8e862736006a15b21b0e7cf8b14e15fe49e3",
    "0.57.13": "b4158eb11a2d53b8c06c1bfcec8ccda4ce8329e65514b8c3a0aa9f58ad30f82f",
    "0.57.14": "aa5c45c69c7a2ce4998a4af38f1c32ef3483fff2871da210eabd3635d199bbde",
  });
  var SELECTORS = Object.freeze({
    sticky_phone: ".performanceLocalV5StickyPhoneBar a",
    sticky_phone_number: ".performanceLocalV5StickyPhoneBar strong",
    sticky_action: ".performanceLocalV5StickyActionBanner a",
    nav_home: '.performanceLocalDesktopNavigation a[href="/"]',
    nav_service: '.performanceLocalDesktopNavigation a[href="/drywood-termite-tenting/"]',
    nav_dropdown: ".performanceLocalDesktopNavigation button",
    mobile_service: '.performanceLocalDrawerList a[href="/drywood-termite-tenting/"]',
    hero_h1: ".performanceLocalHero h1",
    hero_cta: '.performanceLocalHeroActions a[href^="tel:"]',
    lower_body: '[data-source-section-key="why_it_matters"] p',
    lower_conversion: '[data-source-section-key="final_conversion"] p',
  });
  var AFFECTED = Object.freeze([
    "sticky_phone",
    "sticky_action",
    "nav_home",
    "nav_service",
    "nav_dropdown",
    "mobile_service",
  ]);

  function round(value) {
    return Math.round(value * 10000) / 10000;
  }

  function rect(element) {
    var value = element.getBoundingClientRect();
    return {
      x: round(value.x),
      y: round(value.y),
      width: round(value.width),
      height: round(value.height),
      x_fraction: round(value.x - Math.trunc(value.x)),
      y_fraction: round(value.y - Math.trunc(value.y)),
    };
  }

  function ancestorEffects(element) {
    var effects = [];
    var parent = element.parentElement;
    while (parent && parent !== document.documentElement) {
      var style = global.getComputedStyle(parent);
      if (style.transform !== "none" || style.filter !== "none" || style.opacity !== "1") {
        effects.push({
          tag: parent.tagName,
          class_name: String(parent.className || ""),
          transform: style.transform,
          filter: style.filter,
          opacity: style.opacity,
        });
      }
      parent = parent.parentElement;
    }
    return effects;
  }

  function computedTarget(name, selector) {
    var matches = Array.from(document.querySelectorAll(selector));
    var element = matches[0] || null;
    if (!element) return { name: name, selector: selector, count: 0, missing: true };
    var style = global.getComputedStyle(element);
    var box = rect(element);
    return {
      name: name,
      selector: selector,
      count: matches.length,
      text: String(element.textContent || "").trim(),
      accessible_name: element.getAttribute("aria-label") || String(element.textContent || "").trim(),
      font_family: style.fontFamily,
      resolved_loaded_font: style.fontFamily.includes("system-ui")
        ? "system-ui platform-local face"
        : style.fontFamily,
      font_size: style.fontSize,
      font_weight: style.fontWeight,
      font_style: style.fontStyle,
      line_height: style.lineHeight,
      letter_spacing: style.letterSpacing,
      text_shadow: style.textShadow,
      text_stroke: style.getPropertyValue("-webkit-text-stroke"),
      text_rendering: style.getPropertyValue("text-rendering"),
      font_synthesis: style.getPropertyValue("font-synthesis"),
      filter: style.filter,
      opacity: style.opacity,
      transform: style.transform,
      ancestor_effects: ancestorEffects(element),
      rect: box,
      clipped: element.scrollWidth > element.clientWidth + 1
        || element.scrollHeight > element.clientHeight + 1,
      font_available: document.fonts.check(
        style.fontWeight + " " + style.fontSize + " " + style.fontFamily
      ),
    };
  }

  function stylesheetIdentity() {
    var links = Array.from(document.querySelectorAll("#project-atlas-performance-local-v5-css"));
    if (links.length !== 1) return { count: links.length, valid: false };
    var url = new URL(links[0].href, global.location.href);
    var hashes = url.searchParams.getAll("ver");
    var hash = hashes.length === 1 ? hashes[0] : null;
    var version = Object.keys(STYLESHEET_HASH_BY_VERSION).find(function findVersion(candidate) {
      return STYLESHEET_HASH_BY_VERSION[candidate] === hash;
    }) || null;
    return {
      count: links.length,
      hash: hash,
      version: version,
      valid: links[0].relList.contains("stylesheet")
        && url.origin === global.location.origin
        && url.pathname.endsWith("/assets/performance-local-v5.css")
        && url.hash === ""
        && version !== null,
    };
  }

  function add(assertions, code, pass, details) {
    assertions.push({ code: code, pass: Boolean(pass), details: details });
  }

  function run(options) {
    var expectedVersion = options && options.expectedVersion;
    if (!Object.prototype.hasOwnProperty.call(STYLESHEET_HASH_BY_VERSION, expectedVersion)) {
      throw new Error("A supported expectedVersion is required");
    }
    var targets = {};
    Object.keys(SELECTORS).forEach(function measure(name) {
      targets[name] = computedTarget(name, SELECTORS[name]);
    });
    var assertions = [];
    var stylesheet = stylesheetIdentity();
    add(assertions, "stylesheet_identity", stylesheet.valid && stylesheet.version === expectedVersion, stylesheet);
    var customFaces = Array.from(document.fonts).map(function describe(face) {
      return { family: face.family, weight: face.weight, style: face.style, status: face.status };
    });
    var fontResources = global.performance && typeof global.performance.getEntriesByType === "function"
      ? global.performance.getEntriesByType("resource").filter(function isFont(entry) {
        return /(?:font|woff2?|ttf|otf)(?:[?#.]|$)/i.test(entry.name);
      }).map(function name(entry) { return entry.name; })
      : [];
    var affectedCustomFaces = customFaces.filter(function usedByAffectedTarget(face) {
      return AFFECTED.some(function familyContainsFace(name) {
        return targets[name].font_family.toLowerCase().includes(
          String(face.family || "").replace(/[\"']/g, "").toLowerCase()
        );
      });
    });
    add(assertions, "no_font_resource", affectedCustomFaces.length === 0 && fontResources.length === 0, {
      custom_faces: customFaces,
      affected_custom_faces: affectedCustomFaces,
      font_resources: fontResources,
    });

    AFFECTED.forEach(function checkAffected(name) {
      var target = targets[name];
      add(assertions, name + ".exists_once", target.count === 1, { count: target.count });
      add(assertions, name + ".font_available", target.font_available === true, {
        font_family: target.font_family,
        resolved_loaded_font: target.resolved_loaded_font,
      });
      if (expectedVersion === "0.57.13" || expectedVersion === "0.57.14") {
        add(assertions, name + ".system_family", /system-ui/.test(target.font_family), target.font_family);
        add(assertions, name + ".real_weight", target.font_weight === "700", target.font_weight);
        add(assertions, name + ".no_synthesis", target.font_synthesis === "none", target.font_synthesis);
        add(assertions, name + ".no_shadow", target.text_shadow === "none", target.text_shadow);
        add(assertions, name + ".no_stroke", /^0px(?:\s|$)/.test(target.text_stroke), target.text_stroke);
        add(assertions, name + ".no_filter", target.filter === "none", target.filter);
        add(assertions, name + ".full_opacity", target.opacity === "1", target.opacity);
        add(assertions, name + ".no_scale", target.transform === "none", target.transform);
        add(assertions, name + ".no_clipping", target.clipped === false, target.rect);
      }
    });

    var phoneNumber = targets.sticky_phone_number;
    add(assertions, "sticky_phone_number.exists_once", phoneNumber.count === 1, {
      count: phoneNumber.count,
    });
    if (expectedVersion === "0.57.13") {
      add(assertions, "baseline_05713.phone_parent_700_nested_900",
        targets.sticky_phone.font_weight === "700" && phoneNumber.font_weight === "900", {
          parent: targets.sticky_phone.font_weight,
          nested: phoneNumber.font_weight,
        });
    }
    if (expectedVersion === "0.57.14") {
      add(assertions, "successor_05714.phone_parent_nested_match",
        targets.sticky_phone.font_family === phoneNumber.font_family
          && targets.sticky_phone.font_weight === "700"
          && phoneNumber.font_weight === "700", {
          parent_family: targets.sticky_phone.font_family,
          nested_family: phoneNumber.font_family,
          parent_weight: targets.sticky_phone.font_weight,
          nested_weight: phoneNumber.font_weight,
        });
      add(assertions, "successor_05714.phone_number_font_available",
        phoneNumber.font_available === true, phoneNumber.resolved_loaded_font);
      add(assertions, "successor_05714.phone_number_system_family",
        /system-ui/.test(phoneNumber.font_family), phoneNumber.font_family);
      add(assertions, "successor_05714.phone_number_no_synthesis",
        phoneNumber.font_synthesis === "none", phoneNumber.font_synthesis);
      add(assertions, "successor_05714.phone_number_no_shadow",
        phoneNumber.text_shadow === "none", phoneNumber.text_shadow);
      add(assertions, "successor_05714.phone_number_no_stroke",
        /^0px(?:\s|$)/.test(phoneNumber.text_stroke), phoneNumber.text_stroke);
      add(assertions, "successor_05714.phone_number_no_filter",
        phoneNumber.filter === "none", phoneNumber.filter);
      add(assertions, "successor_05714.phone_number_full_opacity",
        phoneNumber.opacity === "1", phoneNumber.opacity);
      add(assertions, "successor_05714.phone_number_no_scale",
        phoneNumber.transform === "none", phoneNumber.transform);
      add(assertions, "successor_05714.phone_number_no_clipping",
        phoneNumber.clipped === false, phoneNumber.rect);
    }

    if (expectedVersion === "0.57.12") {
      add(assertions, "baseline.sticky_uses_900", targets.sticky_phone.font_weight === "900"
        && targets.sticky_action.font_weight === "900", {
        phone: targets.sticky_phone.font_weight,
        action: targets.sticky_action.font_weight,
      });
      add(assertions, "baseline.navigation_uses_750", targets.nav_home.font_weight === "750"
        && targets.nav_service.font_weight === "750"
        && targets.nav_dropdown.font_weight === "750", {
        home: targets.nav_home.font_weight,
        service: targets.nav_service.font_weight,
        dropdown: targets.nav_dropdown.font_weight,
      });
      add(assertions, "baseline.synthesis_enabled", targets.sticky_phone.font_synthesis !== "none"
        && targets.nav_home.font_synthesis !== "none", {
        phone: targets.sticky_phone.font_synthesis,
        navigation: targets.nav_home.font_synthesis,
      });
    }

    add(assertions, "hero_typography_preserved", targets.hero_h1.font_weight === "800"
      && targets.hero_h1.text_shadow !== "none", targets.hero_h1);
    add(assertions, "hero_cta_preserved", targets.hero_cta.font_weight === "850"
      && targets.hero_cta.font_synthesis !== "none", targets.hero_cta);
    add(assertions, "body_typography_preserved", targets.lower_body.font_weight === "300"
      && targets.lower_conversion.font_weight === "300", {
      body: targets.lower_body.font_weight,
      conversion: targets.lower_conversion.font_weight,
    });
    var viewportWidth = document.documentElement.clientWidth;
    var documentWidth = Math.max(document.documentElement.scrollWidth, document.body.scrollWidth);
    add(assertions, "no_horizontal_overflow", documentWidth <= viewportWidth + 1, {
      document_width: documentWidth,
      viewport_width: viewportWidth,
    });

    return {
      result_schema: RESULT_SCHEMA,
      version: expectedVersion,
      viewport: {
        width: global.innerWidth,
        height: global.innerHeight,
        device_scale_factor: global.devicePixelRatio,
        zoom: global.visualViewport ? global.visualViewport.scale : 1,
      },
      stylesheet: stylesheet,
      targets: targets,
      custom_font_faces: customFaces,
      font_resources: fontResources,
      assertions: assertions,
      passed: assertions.every(function passed(assertion) { return assertion.pass; }),
    };
  }

  function scheduleQueryAutorun() {
    var parameters = new URLSearchParams(global.location.search);
    var markers = parameters.getAll("atlas-typography-proof");
    if (markers.length !== 1 || markers[0] !== "1") return;
    var versions = parameters.getAll("atlas-typography-version");
    function autorun() {
      document.documentElement.setAttribute(AUTORUN_ATTRIBUTE, "RUNNING");
      try {
        if (versions.length !== 1) throw new Error("atlas-typography-version must occur exactly once");
        var result = run({ expectedVersion: versions[0] });
        document.documentElement.setAttribute(AUTORUN_ATTRIBUTE, JSON.stringify(result));
      } catch (error) {
        document.documentElement.setAttribute(AUTORUN_ATTRIBUTE, "ERROR");
        if (global.console && typeof global.console.error === "function") {
          global.console.error("Project Atlas V5 typography proof failed.", error);
        }
      }
    }
    if (document.readyState === "complete") global.setTimeout(autorun, 0);
    else global.addEventListener("load", autorun, { once: true });
  }

  global[API_NAME] = Object.freeze({
    autorunAttribute: AUTORUN_ATTRIBUTE,
    resultSchema: RESULT_SCHEMA,
    run: run,
  });
  scheduleQueryAutorun();
})(window);
