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

  function deliveryUuid() {
    if (!window.crypto || typeof window.crypto.getRandomValues !== "function") return null;
    var bytes = new Uint8Array(16);
    window.crypto.getRandomValues(bytes);
    bytes[6] = (bytes[6] & 15) | 64;
    bytes[8] = (bytes[8] & 63) | 128;
    var hex = Array.prototype.map.call(bytes, function (value) {
      return value.toString(16).padStart(2, "0");
    }).join("");
    return hex.slice(0, 8) + "-" + hex.slice(8, 12) + "-" + hex.slice(12, 16) + "-" +
      hex.slice(16, 20) + "-" + hex.slice(20);
  }

  function initializeDeliveryForm(root) {
    var forms = root.querySelectorAll("[data-atlas-v5-active-form]");
    if (forms.length !== 1) return;
    var form = forms[0];
    var submit = form.querySelector("[data-atlas-v5-form-submit]");
    var status = form.querySelector("[data-atlas-v5-form-status]");
    var honeypot = form.querySelector("[data-atlas-v5-honeypot]");
    var controls = Array.prototype.slice.call(form.querySelectorAll("[data-field-key]"));
    var endpointValue = form.getAttribute("data-atlas-v5-form-endpoint");
    if (typeof endpointValue !== "string" || endpointValue.trim() === "") return;
    var endpoint;
    try { endpoint = new URL(endpointValue, window.location.href); }
    catch (error) { return; }
    if (!submit || !status || !honeypot || controls.length < 5 || controls.length > 6 ||
        endpoint.origin !== window.location.origin || !/^https?:$/.test(endpoint.protocol)) return;

    var systemKeys = [
      "token", "website_identity", "form_identity", "form_version",
      "page_identity", "field_definition_hash"
    ];
    var system = {};
    for (var index = 0; index < systemKeys.length; index += 1) {
      var key = systemKeys[index];
      var input = form.querySelector("[data-atlas-v5-system='" + key + "']");
      if (!input || typeof input.value !== "string" || input.value === "") return;
      system[key] = input.value;
    }
    var fieldKeys = controls.map(function (control) { return control.getAttribute("data-field-key"); });
    if (fieldKeys.some(function (key, index) { return !key || fieldKeys.indexOf(key) !== index; })) return;
    var fieldErrors = {};
    for (var fieldIndex = 0; fieldIndex < controls.length; fieldIndex += 1) {
      var fieldControl = controls[fieldIndex];
      var fieldKey = fieldKeys[fieldIndex];
      var fieldRule = fieldControl.getAttribute("data-validation-rule");
      var fieldMinimum = Number(fieldControl.getAttribute("data-validation-minimum-length"));
      var fieldMaximum = Number(fieldControl.getAttribute("data-validation-maximum-length"));
      var fieldLabel = fieldControl.closest("label");
      var fieldError = fieldLabel ? fieldLabel.querySelector("[data-atlas-v5-field-error]") : null;
      if (!fieldRule || !Number.isInteger(fieldMinimum) || fieldMinimum < 0 ||
          !Number.isInteger(fieldMaximum) || fieldMaximum < fieldMinimum ||
          !fieldError || !fieldError.id) return;
      fieldErrors[fieldKey] = fieldError;
    }
    var formVersion = Number(system.form_version);
    if (!Number.isInteger(formVersion) || formVersion < 1) return;

    var pending = false;
    var attemptIdentity = null;
    var failedAttempt = false;

    function setFocusRisk(value) {
      root.setAttribute("data-v5-form-focus-risk", value ? "true" : "false");
    }

    function showStatus(state, message) {
      status.hidden = false;
      status.textContent = message;
      status.setAttribute("data-v5-form-state", state);
      form.setAttribute("data-visual-state", state === "success" || state === "duplicate" ? "success" :
        state === "loading" ? "loading" : "error");
      status.classList.toggle("performanceLocalFormStateSuccess", state === "success" || state === "duplicate");
      status.classList.toggle("performanceLocalFormStateError", state !== "success" && state !== "duplicate" && state !== "loading");
      if (state !== "loading") {
        try { status.focus({ preventScroll: true }); }
        catch (error) { status.focus(); }
      }
    }

    function setPending(value) {
      pending = value;
      submit.disabled = value;
      form.setAttribute("aria-busy", value ? "true" : "false");
      form.setAttribute("data-v5-form-pending", value ? "true" : "false");
    }

    function controlFailsGovernedValidation(control) {
      var value = control.value.replace(/\r\n?/g, "\n").trim();
      var rule = control.getAttribute("data-validation-rule");
      var minimum = Number(control.getAttribute("data-validation-minimum-length"));
      var maximum = Number(control.getAttribute("data-validation-maximum-length"));
      if (rule !== "free_text" && value.indexOf("\n") !== -1) return true;
      if (rule === "free_text" ? /[\x00-\x09\x0B-\x1F\x7F]/.test(value) : /[\x00-\x1F\x7F]/.test(value)) return true;
      if (value === "" && !control.required) return false;
      if (value.length < minimum || value.length > maximum || control.required && value === "") return true;
      if (rule === "phone") {
        return !/^[0-9+(). xXextEXT-]+$/.test(value) || (value.match(/[0-9]/g) || []).length < 6;
      }
      if (rule === "postal_code") return !/^[A-Za-z0-9][A-Za-z0-9 -]{3,10}[A-Za-z0-9]$/.test(value);
      if (rule === "email_address") return value !== "" && control.validity.typeMismatch;
      return false;
    }

    function clearValidationState(control) {
      if (control.getAttribute("aria-invalid") !== "true") return;
      var key = control.getAttribute("data-field-key");
      var error = fieldErrors[key];
      control.removeAttribute("aria-invalid");
      if (error) {
        error.hidden = true;
        var describedBy = (control.getAttribute("aria-describedby") || "").split(/\s+/).filter(function (id) {
          return id && id !== error.id;
        });
        if (describedBy.length) control.setAttribute("aria-describedby", describedBy.join(" "));
        else control.removeAttribute("aria-describedby");
      }
    }

    function markValidationErrors() {
      var firstInvalid = null;
      controls.forEach(function (control) {
        if (!controlFailsGovernedValidation(control)) return;
        var key = control.getAttribute("data-field-key");
        var error = fieldErrors[key];
        control.setAttribute("aria-invalid", "true");
        if (error) {
          error.hidden = false;
          var describedBy = (control.getAttribute("aria-describedby") || "").split(/\s+/).filter(Boolean);
          if (describedBy.indexOf(error.id) === -1) describedBy.push(error.id);
          control.setAttribute("aria-describedby", describedBy.join(" "));
        }
        if (!firstInvalid) firstInvalid = control;
      });
      return firstInvalid;
    }

    function focusFirstInvalid(control) {
      if (!control) return;
      var applyFocus = function () {
        if (!control.isConnected || control.getAttribute("aria-invalid") !== "true") return;
        control.scrollIntoView({ behavior: "auto", block: "center", inline: "nearest" });
        try { control.focus({ preventScroll: true }); }
        catch (error) { control.focus(); }
      };
      if (typeof window.requestAnimationFrame === "function") {
        window.requestAnimationFrame(applyFocus);
      } else {
        window.setTimeout(applyFocus, 0);
      }
    }

    form.addEventListener("focusin", function () { setFocusRisk(true); });
    form.addEventListener("focusout", function () {
      window.setTimeout(function () {
        if (!form.contains(document.activeElement)) setFocusRisk(false);
      }, 0);
    });
    form.addEventListener("input", function (event) {
      if (event.target && event.target.matches("[data-field-key]")) {
        clearValidationState(event.target);
      }
      if (!pending && failedAttempt) {
        attemptIdentity = null;
        failedAttempt = false;
      }
    });
    submit.disabled = false;

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      if (pending) return;
      if (!attemptIdentity) attemptIdentity = deliveryUuid();
      if (!attemptIdentity) {
        showStatus("client_failure", "The estimate request could not be sent. Please try again.");
        return;
      }
      var fields = {};
      controls.forEach(function (control) {
        fields[control.getAttribute("data-field-key")] = control.value;
      });
      var requestBody = {
        token: system.token,
        idempotency_identity: attemptIdentity,
        website_identity: system.website_identity,
        form_identity: system.form_identity,
        form_version: formVersion,
        page_identity: system.page_identity,
        field_definition_hash: system.field_definition_hash,
        honeypot: honeypot.value,
        fields: fields
      };
      setPending(true);
      showStatus("loading", "Sending your estimate request…");
      window.fetch(endpoint.href, {
        method: "POST",
        headers: { "Accept": "application/json", "Content-Type": "application/json" },
        body: JSON.stringify(requestBody),
        credentials: "same-origin",
        cache: "no-store",
        redirect: "error"
      }).then(function (response) {
        return response.json().catch(function () { return null; }).then(function (result) {
          return { response: response, result: result };
        });
      }).then(function (outcome) {
        var response = outcome.response;
        var result = outcome.result;
        var keys = result && typeof result === "object" ? Object.keys(result).sort().join(",") : "";
        var successful = response.ok && response.status === 200 && result && result.ok === true &&
          (result.state === "success" || result.state === "duplicate");
        var knownFailure = !response.ok && result && result.ok === false && (
          response.status === 409 && result.state === "pending" ||
          response.status === 422 && result.state === "validation_error" ||
          response.status === 429 && result.state === "rate_limited" ||
          response.status === 503 && result.state === "mail_failure"
        );
        if (keys !== "message,ok,state" || typeof result.message !== "string" ||
            (!successful && !knownFailure)) {
          throw new Error("invalid-response");
        }
        showStatus(result.state, result.message);
        var firstInvalid = result.state === "validation_error" ? markValidationErrors() : null;
        focusFirstInvalid(firstInvalid);
        if (successful) {
          controls.forEach(function (control) {
            var key = control.getAttribute("data-field-key");
            if (control.value === requestBody.fields[key]) control.value = "";
          });
          if (honeypot.value === requestBody.honeypot) honeypot.value = "";
          attemptIdentity = null;
          failedAttempt = false;
        } else {
          failedAttempt = true;
        }
      }).catch(function () {
        failedAttempt = true;
        showStatus("client_failure", "The estimate request could not be sent. Please try again.");
      }).finally(function () {
        setPending(false);
      });
    });
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

    initializeDeliveryForm(root);

    Array.prototype.forEach.call(
      root.querySelectorAll("[data-atlas-v5-inert-form]"),
      function (form) {
        form.addEventListener("submit", function (event) { event.preventDefault(); });
      }
    );

    var backToTop = root.querySelector("[data-atlas-v5-back-to-top]");
    if (backToTop) {
      var footer = root.querySelector("footer");
      var formCollisionTargets = root.querySelectorAll("[data-atlas-v5-inert-form], [data-atlas-v5-active-form]");
      var backToTopIntersectsForm = function () {
        var style = window.getComputedStyle(backToTop);
        var controlRight = parseFloat(style.right) || 0;
        var controlBottom = parseFloat(style.bottom) || 0;
        var controlWidth = parseFloat(style.width) || 48;
        var controlHeight = Math.max(parseFloat(style.height) || 0, parseFloat(style.minHeight) || 48);
        var collisionPadding = 12;
        var collisionLeft = window.innerWidth - controlRight - controlWidth - collisionPadding;
        var collisionTop = window.innerHeight - controlBottom - controlHeight - collisionPadding;
        return Array.prototype.some.call(formCollisionTargets, function (form) {
          var bounds = form.getBoundingClientRect();
          return bounds.right >= collisionLeft && bounds.left <= window.innerWidth &&
            bounds.bottom >= collisionTop && bounds.top <= window.innerHeight;
        });
      };
      var setBackToTopHidden = function (hidden) {
        backToTop.hidden = hidden;
        if (hidden) {
          backToTop.setAttribute("aria-hidden", "true");
          if (document.activeElement === backToTop) backToTop.blur();
        } else {
          backToTop.removeAttribute("aria-hidden");
        }
      };
      var updateBackToTop = function () {
        var belowThreshold = window.scrollY < Math.max(480, window.innerHeight * 0.75);
        var menuOpen = root.getAttribute("data-v5-menu-open") === "true";
        var formFocused = root.querySelector("[data-atlas-v5-inert-form]:focus-within, [data-atlas-v5-active-form]:focus-within") !== null;
        var footerReached = footer && footer.getBoundingClientRect().top <= window.innerHeight;
        var formCollision = backToTopIntersectsForm();
        setBackToTopHidden(belowThreshold || menuOpen || formFocused || formCollision || Boolean(footerReached));
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
