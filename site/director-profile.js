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
      films.length + (films.length === 1 ? " film" : " films") + " in the current Classics dataset.";

    var listEl = document.getElementById("dir-filmography-list");
    var filmTpl = document.getElementById("dir-film-card-template");

    var posterMap = window.POSTER_MAP || {};

    films.forEach(function (film) {
      var card = filmTpl.content.firstElementChild.cloneNode(true);
      var posterImg = card.querySelector(".film-poster img");
      var posterSrc = posterMap[film.t];
      if (posterSrc) {
        posterImg.src = posterSrc;
        posterImg.alt = film.title + " poster";
      }
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
    // Edge-graph clusters (shared-actor network, drawn with connecting lines --
    // see cluster.vizSvg naming in CLUSTER_VIZ_SVG) get a smaller highlight
    // scale than ring clusters so the enlarged node doesn't swallow its edges.
    if (/_graph\.svg$/.test(cluster.vizSvg || "")) {
      card.classList.add("dir-viz-card--edges");
    }
    card.querySelector(".dir-viz-swatch").setAttribute("style", swatchStyle(cluster.color));
    card.querySelector(".dir-viz-card-title").textContent = cluster.name;
    card.querySelector(".dir-viz-count").textContent =
      highlighted.length + " of " + cluster.filmCount + (cluster.filmCount === 1 ? " film" : " films");
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
    pinAndDeclutterLabels(svg, highlightSet);
  }

  var SVG_NS = "http://www.w3.org/2000/svg";

  // Permanently reveals the title label for each of this director's own
  // (highlighted) films instead of requiring hover, and nudges any that
  // collide apart so no two labels overlap -- other films in the cluster
  // keep the existing hover-to-reveal behavior untouched. A label that had
  // to move more than a few px to clear a collision gets a thin dashed
  // leader line back to its node, since a nudged label can otherwise land
  // far enough away to stop reading as "this node's title."
  function pinAndDeclutterLabels(svg, highlightSet) {
    var viewBox = svg.viewBox.baseVal;
    var margin = 6;
    var minX = viewBox.x + margin;
    var minY = viewBox.y + margin;
    var maxX = viewBox.x + viewBox.width - margin;
    var maxY = viewBox.y + viewBox.height - margin;
    var firstLabelEl = svg.querySelector('[id^="t-"]');

    var boxes = [];
    Object.keys(highlightSet).forEach(function (tconst) {
      var label = svg.querySelector("#" + CSS.escape("t-" + tconst));
      var nodeEl = svg.querySelector("#" + CSS.escape("n-" + tconst));
      if (!label || !nodeEl) return;
      label.classList.add("dh-label-pinned");

      var nodePolygon = nodeEl.tagName.toLowerCase() === "polygon" ? nodeEl : nodeEl.querySelector("polygon");
      var nodeBox = (nodePolygon || nodeEl).getBBox();
      var labelBox = label.getBBox();
      boxes.push({
        label: label,
        x: labelBox.x, y: labelBox.y, w: labelBox.width, h: labelBox.height,
        dx: 0, dy: 0,
        nodeCx: nodeBox.x + nodeBox.width / 2,
        nodeCy: nodeBox.y + nodeBox.height / 2
      });
    });
    if (!boxes.length) return;

    // Iteratively push apart any pair of pinned label boxes that overlap,
    // along whichever axis has the smaller overlap.
    for (var iter = 0; iter < 200; iter++) {
      var moved = false;
      for (var i = 0; i < boxes.length; i++) {
        for (var j = i + 1; j < boxes.length; j++) {
          var a = boxes[i], b = boxes[j];
          var ax1 = a.x + a.dx, ay1 = a.y + a.dy, ax2 = ax1 + a.w, ay2 = ay1 + a.h;
          var bx1 = b.x + b.dx, by1 = b.y + b.dy, bx2 = bx1 + b.w, by2 = by1 + b.h;
          var overlapX = Math.min(ax2, bx2) - Math.max(ax1, bx1);
          var overlapY = Math.min(ay2, by2) - Math.max(ay1, by1);
          if (overlapX > 0 && overlapY > 0) {
            moved = true;
            if (overlapX < overlapY) {
              var shiftX = overlapX / 2 + 1;
              if (ax1 < bx1) { a.dx -= shiftX; b.dx += shiftX; } else { a.dx += shiftX; b.dx -= shiftX; }
            } else {
              var shiftY = overlapY / 2 + 1;
              if (ay1 < by1) { a.dy -= shiftY; b.dy += shiftY; } else { a.dy += shiftY; b.dy -= shiftY; }
            }
          }
        }
      }
      if (!moved) break;
    }

    var leaders = document.createElementNS(SVG_NS, "g");
    leaders.setAttribute("class", "dh-leaders");
    var leaderThreshold = 16;
    var anyLeaders = false;

    boxes.forEach(function (box) {
      var nx = Math.min(Math.max(box.x + box.dx, minX), maxX - box.w);
      var ny = Math.min(Math.max(box.y + box.dy, minY), maxY - box.h);
      box.dx = nx - box.x;
      box.dy = ny - box.y;

      if (box.dx || box.dy) {
        box.label.setAttribute("transform", "translate(" + box.dx.toFixed(1) + "," + box.dy.toFixed(1) + ")");
      }

      var displacement = Math.sqrt(box.dx * box.dx + box.dy * box.dy);
      if (displacement > leaderThreshold) {
        var rx1 = box.x + box.dx, ry1 = box.y + box.dy;
        var rx2 = rx1 + box.w, ry2 = ry1 + box.h;
        var targetX = Math.min(Math.max(box.nodeCx, rx1), rx2);
        var targetY = Math.min(Math.max(box.nodeCy, ry1), ry2);
        var line = document.createElementNS(SVG_NS, "line");
        line.setAttribute("class", "dh-leader");
        line.setAttribute("x1", box.nodeCx.toFixed(1));
        line.setAttribute("y1", box.nodeCy.toFixed(1));
        line.setAttribute("x2", targetX.toFixed(1));
        line.setAttribute("y2", targetY.toFixed(1));
        leaders.appendChild(line);
        anyLeaders = true;
      }
    });

    if (anyLeaders) {
      if (firstLabelEl) svg.insertBefore(leaders, firstLabelEl);
      else svg.appendChild(leaders);
    }
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
