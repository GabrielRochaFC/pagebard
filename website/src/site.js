// Pagebard website: language memory and copy buttons. Runs without network access or tracking.
(function () {
  var KEY = "pagebard-lang";
  var PATHS = { en: "", "pt-BR": "pt-br/", es: "es/" };

  function store(lang) {
    try { localStorage.setItem(KEY, lang); } catch (e) { /* storage unavailable */ }
  }
  function stored() {
    try { return localStorage.getItem(KEY); } catch (e) { return null; }
  }

  // On the English (root) page only: send a first-time visitor to their browser's language.
  var root = document.documentElement;
  if (root.lang === "en" && !stored()) {
    var wanted = (navigator.languages && navigator.languages[0]) || navigator.language || "";
    wanted = wanted.toLowerCase();
    var target = wanted.indexOf("pt") === 0 ? "pt-BR" : wanted.indexOf("es") === 0 ? "es" : null;
    if (target) {
      store(target);
      location.replace(PATHS[target] + location.hash);
      return;
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    // Remember an explicit language choice.
    document.querySelectorAll("a[hreflang]").forEach(function (a) {
      a.addEventListener("click", function () { store(a.getAttribute("hreflang")); });
    });

    // Copy buttons for terminal commands.
    if (!navigator.clipboard) return;
    var label = document.body.dataset.copy;
    var done = document.body.dataset.copied;
    document.querySelectorAll(".code").forEach(function (box) {
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "copy";
      btn.textContent = label;
      btn.addEventListener("click", function () {
        navigator.clipboard.writeText(box.querySelector("code").textContent).then(function () {
          btn.textContent = done;
          setTimeout(function () { btn.textContent = label; }, 1600);
        });
      });
      box.appendChild(btn);
    });
  });
})();
