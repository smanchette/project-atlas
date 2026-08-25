(function () {
  "use strict";

  function focusable(container) {
    return Array.prototype.filter.call(
      container.querySelectorAll("a[href], button:not([disabled]), [tabindex]:not([tabindex='-1'])"),
      function (element) {
        return !element.closest("[hidden]") &&
          element.getAttribute("aria-hidden") !== "true" &&
          element.getClientRects().length > 0;
      }
    );
  }

  function initializeRoot(root) {
    var trigger = root.querySelector("[data-atlas-v5-menu-toggle]");
    var backdrop = root.querySelector("[data-atlas-v5-menu-backdrop]");
    var drawer = root.querySelector("[data-atlas-v5-mobile-nav]");
    var closeButton = root.querySelector("[data-atlas-v5-menu-close]");
    var legacySite = root.querySelector(".performanceLocalSite[data-mobile-menu-open]");
    var header = root.querySelector(".performanceLocalHeader[data-v5-menu-open], .performanceLocalV5Header[data-v5-menu-open]");
    var previousOverflow = "";

    function setMenuState(open) {
      var value = open ? "true" : "false";
      root.setAttribute("data-v5-menu-open", value);
      if (legacySite) legacySite.setAttribute("data-mobile-menu-open", value);
      if (header) header.setAttribute("data-v5-menu-open", value);
    }

    function closeMenu(restoreFocus) {
      if (!trigger || !backdrop || !drawer) return;
      trigger.setAttribute("aria-expanded", "false");
      setMenuState(false);
      backdrop.hidden = true;
      drawer.hidden = true;
      document.body.style.overflow = previousOverflow;
      if (restoreFocus) trigger.focus();
    }

    function openMenu() {
      if (!trigger || !backdrop || !drawer) return;
      previousOverflow = document.body.style.overflow;
      trigger.setAttribute("aria-expanded", "true");
      setMenuState(true);
      backdrop.hidden = false;
      drawer.hidden = false;
      document.body.style.overflow = "hidden";
      var values = focusable(drawer);
      if (values.length) values[0].focus();
    }

    if (trigger && backdrop && drawer) {
      setMenuState(false);
      trigger.addEventListener("click", function () {
        if (trigger.getAttribute("aria-expanded") === "true") closeMenu(true);
        else openMenu();
      });
      backdrop.addEventListener("click", function (event) {
        if (event.target === backdrop) closeMenu(true);
      });
      if (closeButton) closeButton.addEventListener("click", function () { closeMenu(true); });
      drawer.addEventListener("click", function (event) {
        if (event.target.closest("a[href]")) closeMenu(false);
      });
      document.addEventListener("keydown", function (event) {
        if (trigger.getAttribute("aria-expanded") !== "true") return;
        if (event.key === "Escape") {
          event.preventDefault();
          closeMenu(true);
          return;
        }
        if (event.key !== "Tab") return;
        var values = focusable(drawer);
        if (!values.length) return;
        var first = values[0];
        var last = values[values.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      });
    }

    Array.prototype.forEach.call(
      root.querySelectorAll("[data-atlas-v5-submenu-toggle]"),
      function (button) {
        var controlled = button.getAttribute("aria-controls");
        var menu = controlled ? document.getElementById(controlled) : null;
        if (!menu || !root.contains(menu)) return;
        button.addEventListener("click", function () {
          var expanded = button.getAttribute("aria-expanded") === "true";
          button.setAttribute("aria-expanded", expanded ? "false" : "true");
          menu.hidden = expanded;
        });
        button.addEventListener("keydown", function (event) {
          if (event.key !== "Escape") return;
          button.setAttribute("aria-expanded", "false");
          menu.hidden = true;
          button.focus();
        });
      }
    );

    Array.prototype.forEach.call(
      root.querySelectorAll("[data-atlas-v5-inert-form]"),
      function (form) {
        form.addEventListener("submit", function (event) { event.preventDefault(); });
      }
    );

    var backToTop = root.querySelector("[data-atlas-v5-back-to-top]");
    if (backToTop) {
      var footer = root.querySelector("footer");
      var updateBackToTop = function () {
        var belowThreshold = window.scrollY < Math.max(480, window.innerHeight * 0.75);
        var menuOpen = root.getAttribute("data-v5-menu-open") === "true";
        var formFocused = root.querySelector("[data-atlas-v5-inert-form]:focus-within") !== null;
        var footerReached = footer && footer.getBoundingClientRect().top <= window.innerHeight;
        backToTop.hidden = belowThreshold || menuOpen || formFocused || Boolean(footerReached);
      };
      updateBackToTop();
      window.addEventListener("scroll", updateBackToTop, { passive: true });
      window.addEventListener("resize", updateBackToTop);
      root.addEventListener("focusin", updateBackToTop);
      root.addEventListener("focusout", function () { window.setTimeout(updateBackToTop, 0); });
      backToTop.addEventListener("click", function () {
        var reducedMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
        window.scrollTo({ top: 0, behavior: reducedMotion ? "auto" : "smooth" });
      });
    }
  }

  function initialize() {
    Array.prototype.forEach.call(
      document.querySelectorAll("[data-project-atlas-v5-root]"),
      initializeRoot
    );
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", initialize);
  else initialize();
})();
