/* Defensive, install-safe brand replacement. Runs after render, so it
   can never break module installation the way a wrong QWeb xpath
   could. It is a best-effort visual pass, not a guarantee every
   occurrence is caught - always eyeball the login page, tab title and
   one real email after deploying to a customer. */
(function () {
    "use strict";

    var BRAND_NAME = window.AI_BRAND_NAME || document.documentElement.getAttribute("data-ai-brand") || "Company AI";

    function replaceText(root) {
        var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null);
        var node;
        while ((node = walker.nextNode())) {
            if (node.nodeValue && node.nodeValue.indexOf("Odoo") !== -1) {
                node.nodeValue = node.nodeValue.split("Odoo").join(BRAND_NAME);
            }
        }
        document.title = document.title.split("Odoo").join(BRAND_NAME);
    }

    function run() {
        try {
            replaceText(document.body);
        } catch (e) {
            // never let a debranding pass throw and break the page
            console.warn("debrand.js: skipped a pass", e);
        }
    }

    document.addEventListener("DOMContentLoaded", run);

    // Odoo's web client re-renders parts of the DOM after load (SPA),
    // so keep watching - but disconnect while we run our own pass and
    // debounce, otherwise our own text replacement would re-trigger
    // the observer and loop forever.
    var debounceTimer = null;
    var observer = new MutationObserver(function () {
        if (debounceTimer) {
            clearTimeout(debounceTimer);
        }
        debounceTimer = setTimeout(function () {
            observer.disconnect();
            run();
            observer.observe(document.body, {childList: true, subtree: true});
        }, 400);
    });
    document.addEventListener("DOMContentLoaded", function () {
        observer.observe(document.body, {childList: true, subtree: true});
    });
})();
