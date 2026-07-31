// Renders a director profile page (site/director.html?director=<slug>) from
// window.FILMS + window.DIRECTOR_INFO + DirectorUtils.
(function () {
  "use strict";

  var U = window.DirectorUtils;
  var index = U.buildIndex(window.FILMS);
  var filmsByT = U.filmsByTconst(window.FILMS);
  var info = window.DIRECTOR_INFO || {};

  var params = new URLSearchParams(window.location.search);
  var slug = params.get("director") || "";
  var director = index.directors[slug];

  var notFoundEl = document.getElementById("dir-not-found");
  var profileEl = document.getElementById("dir-profile");

  if (!director) {
    document.title = "Director not found — Criterion Clusters";
    notFoundEl.hidden = false;
    return;
  }

  document.title = director.name + " — Criterion Clusters";
  profileEl.hidden = false;

  var directorClusters = index.clusters.filter(function (c) {
    return director.filmsByCluster[c.id] && director.filmsByCluster[c.id].length > 0;
  });

  // ── Right column: identity ──────────────────────────────────────────
  document.getElementById("dir-name").textContent = director.name;
  document.getElementById("dir-filmography-name").textContent = director.name;

  var meta = info[slug] || {};
  var portraitEl = document.getElementById("dir-portrait");
  var creditEl = document.getElementById("dir-portrait-credit");
  if (meta.image && meta.imageAlt) {
    portraitEl.src = meta.image;
    portraitEl.alt = meta.imageAlt;
  } else {
    portraitEl.src = "assets/director-placeholder.svg";
    portraitEl.alt = "";
  }
  if (meta.credit) {
    creditEl.textContent = meta.credit;
    creditEl.hidden = false;
  }

  document.getElementById("dir-bio").textContent = meta.bio && meta.bio.trim()
    ? meta.bio
    : "Biography coming soon.";

  var chipTpl = document.getElementById("dir-chip-template");
  var chipList = document.getElementById("dir-cluster-chips");
  directorClusters.forEach(function (cluster) {
    var chip = chipTpl.content.firstElementChild.cloneNode(true);
    chip.querySelector(".dir-chip-swatch").setAttribute("style", swatchStyle(cluster.color));
    chip.querySelector(".dir-chip-name").textContent = cluster.name;
    chip.querySelector(".dir-chip-link").href = "movie-map.html#cluster-" + cluster.id;
    chipList.appendChild(chip);
  });

  // ── Left column: one visualization per cluster ──────────────────────
  var vizList = document.getElementById("dir-viz-list");
  var vizTpl = document.getElementById("dir-viz-card-template");
  var fallbackTpl = document.getElementById("dir-viz-fallback-template");

  directorClusters.forEach(function (cluster) {
    var highlighted = director.filmsByCluster[cluster.id] || [];
    if (cluster.vizSvg) {
      renderVizCard(cluster, highlighted);
    } else {
      renderFallbackCard(cluster, highlighted);
    }
  });

  function swatchStyle(color) {
    var style = "background:" + color;
    if (color && color.toLowerCase() === "#ffffff") style += ";border:1px solid #5a5a5a";
    return style;
  }

  // ── Filmography: every film this director has in the dataset, oldest
  // to newest, ties broken alphabetically. Deduplicated by tconst (a
  // director's film list is already a de-duplicated set, see
  // director-utils.js buildIndex). ─────────────────────────────────────
  (function renderFilmography() {
    var films = director.tconsts
      .map(function (t) { return filmsByT[t]; })
      .filter(Boolean)
      .sort(function (a, b) { return a.year - b.year || a.title.localeCompare(b.title); });

    document.getElementById("dir-filmography-count").textContent =
      films.length + (films.length === 1 ? " film" : " films") + " in the current Criterion dataset.";

    var listEl = document.getElementById("dir-filmography-list");
    var filmTpl = document.getElementById("dir-film-card-template");

    films.forEach(function (film) {
      var card = filmTpl.content.firstElementChild.cloneNode(true);
      var titleEl = card.querySelector(".film-card-title");
      titleEl.textContent = film.title + " ";
      var yearSpan = document.createElement("span");
      yearSpan.className = "film-card-year";
      yearSpan.textContent = "(" + film.year + ")";
      titleEl.appendChild(yearSpan);

      card.querySelector(".film-card-dot").setAttribute("style", swatchStyle(film.color));
      card.querySelector(".film-card-cluster-name").textContent = film.clusterName;

      var link = card.querySelector(".film-card-link");
      var url = film.criterionUrl || film.channelUrl;
      if (url) {
        link.href = url;
      } else {
        link.remove();
      }

      listEl.appendChild(card);
    });
  })();

  function renderVizCard(cluster, highlighted) {
    var card = vizTpl.content.firstElementChild.cloneNode(true);
    card.style.setProperty("--cluster-color", cluster.color);
    card.querySelector(".dir-viz-swatch").setAttribute("style", swatchStyle(cluster.color));
    card.querySelector(".dir-viz-card-title").textContent = cluster.name;
    card.querySelector(".dir-viz-count").textContent =
      highlighted.length + " of " + cluster.filmCount + (cluster.filmCount === 1 ? " film" : " films");
    card.querySelector(".dir-legend-highlight-text").textContent =
      "Directed by " + director.name;
    var embed = card.querySelector(".dir-viz-embed");
    vizList.appendChild(card);
    loadAndHighlightSvg(embed, "assets/" + cluster.vizSvg, cluster.id, highlighted, cluster.name);
  }

  function renderFallbackCard(cluster, highlighted) {
    var card = fallbackTpl.content.firstElementChild.cloneNode(true);
    card.style.setProperty("--cluster-color", cluster.color);
    card.querySelector(".dir-viz-swatch").setAttribute("style", swatchStyle(cluster.color));
    card.querySelector(".dir-viz-card-title").textContent = cluster.name;
    card.querySelector(".dir-viz-count").textContent =
      highlighted.length + " of " + cluster.filmCount + (cluster.filmCount === 1 ? " film" : " films");

    var tagList = card.querySelector(".dir-viz-filmtags");
    highlighted
      .map(function (t) { return filmsByT[t]; })
      .filter(Boolean)
      .sort(function (a, b) { return a.year - b.year || a.title.localeCompare(b.title); })
      .forEach(function (film) {
        var li = document.createElement("li");
        var text = film.title + " (" + film.year + ")";
        var url = film.criterionUrl || film.channelUrl;
        if (url) {
          var a = document.createElement("a");
          a.href = url;
          a.target = "_blank";
          a.rel = "noopener";
          a.textContent = text;
          li.appendChild(a);
        } else {
          li.textContent = text;
        }
        tagList.appendChild(li);
      });

    vizList.appendChild(card);
  }

  // Loads a cluster's fallback SVG (see src/build_svg_fallback.py) via a
  // plain <script> tag rather than fetch(). Regular resource loads like
  // this aren't subject to the file:// restriction fetch() runs into, so
  // this is what makes the visualization work when the page is opened
  // directly from disk instead of through a local/GitHub Pages server.
  var fallbackLoads = Object.create(null);
  function loadSvgFallbackText(clusterId) {
    if (window.__SVG_FALLBACK__ && window.__SVG_FALLBACK__[clusterId]) {
      return Promise.resolve(window.__SVG_FALLBACK__[clusterId]);
    }
    if (!fallbackLoads[clusterId]) {
      fallbackLoads[clusterId] = new Promise(function (resolve, reject) {
        var script = document.createElement("script");
        script.src = "assets/svg-fallback/" + clusterId + ".js";
        script.onload = function () {
          var text = window.__SVG_FALLBACK__ && window.__SVG_FALLBACK__[clusterId];
          if (text) resolve(text);
          else reject(new Error("fallback script loaded but had no entry for " + clusterId));
        };
        script.onerror = function () { reject(new Error("could not load fallback script for " + clusterId)); };
        document.head.appendChild(script);
      });
    }
    return fallbackLoads[clusterId];
  }

  // Turns raw SVG source into the highlighted/dimmed node network and
  // drops it into `container`. The node positions, shapes, colors and
  // geometry all come straight from the real asset used on
  // site/clusters/<id>.html -- nothing here is redrawn.
  function renderSvgInto(container, svgText, highlightSet, clusterName) {
    var doc = new DOMParser().parseFromString(svgText, "image/svg+xml");
    var svg = doc.documentElement;
    if (!svg || svg.nodeName !== "svg") throw new Error("bad svg");

    svg.removeAttribute("width");
    svg.removeAttribute("height");
    svg.classList.add("dir-svg");
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", clusterName + " cluster network, with this director's films highlighted");

    var focusRules = [];
    var nodes = svg.querySelectorAll('[id^="n-"]');
    nodes.forEach(function (el) {
      var tconst = el.id.slice(2);
      var polygon = el.tagName.toLowerCase() === "polygon" ? el : el.querySelector("polygon");
      if (!polygon) return;
      var film = filmsByT[tconst];
      var label = film ? film.title + " (" + film.year + ")" : "";
      var isHighlighted = !!highlightSet[tconst];

      polygon.classList.add("dh-node");
      polygon.classList.add(isHighlighted ? "dh-highlight" : "dh-dim");

      el.setAttribute("tabindex", isHighlighted ? "0" : "-1");
      if (el.tagName.toLowerCase() !== "a") el.setAttribute("role", "img");
      if (label) el.setAttribute("aria-label", label + (isHighlighted ? ", directed by this filmmaker" : ""));

      if (isHighlighted) {
        focusRules.push("#" + CSS.escape(el.id) + ":focus ~ #" + CSS.escape("t-" + tconst) + " { opacity: 1; }");
      }
    });

    if (focusRules.length) {
      var style = doc.createElementNS("http://www.w3.org/2000/svg", "style");
      style.textContent = focusRules.join(" ");
      svg.appendChild(style);
    }

    container.innerHTML = "";
    container.appendChild(svg);
  }

  // Tries fetch() first (efficient: only downloads the clusters a director
  // actually appears in) and falls back to the <script>-tag-loaded copy if
  // fetch() can't reach local files, which happens when this page is
  // opened as a file:// URL instead of served over http(s).
  function loadAndHighlightSvg(container, url, clusterId, highlightedTconsts, clusterName) {
    var highlightSet = Object.create(null);
    highlightedTconsts.forEach(function (t) { highlightSet[t] = true; });

    fetch(url)
      .then(function (res) {
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.text();
      })
      .catch(function () { return loadSvgFallbackText(clusterId); })
      .then(function (svgText) { renderSvgInto(container, svgText, highlightSet, clusterName); })
      .catch(function () {
        container.innerHTML =
          '<p class="dir-viz-error">Visualization unavailable right now — ' +
          "please try reloading the page.</p>";
      });
  }
})();
