// SPDX-License-Identifier: MIT
// Copyright 2024 Lee Bussy; adapted from WsprryPi-Docs.
(function () {
    "use strict";

    function initializeMobileNavigation() {
        var toggle = document.querySelector(".wy-nav-top-toggle");
        var label = toggle && toggle.querySelector(".visually-hidden");

        if (!toggle || !label) {
            return;
        }

        function isOpen() {
            var shifted = document.querySelector(".wy-nav-content-wrap.shift");
            return Boolean(shifted);
        }

        function synchronizeState() {
            var open = isOpen();
            toggle.setAttribute("aria-expanded", String(open));
            label.textContent = open ? "Close navigation menu" : "Open navigation menu";
        }

        toggle.addEventListener("click", function () {
            window.setTimeout(synchronizeState, 0);
        });

        document.addEventListener("keydown", function (event) {
            if (event.key !== "Escape" || !isOpen()) {
                return;
            }

            document.querySelectorAll("[data-toggle='wy-nav-shift'], [data-toggle='rst-versions']")
                .forEach(function (element) {
                    element.classList.remove("shift");
                });
            synchronizeState();
            toggle.focus();
        });

        synchronizeState();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initializeMobileNavigation);
    } else {
        initializeMobileNavigation();
    }
}());
