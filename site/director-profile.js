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
    // Must match the .dh-highlight / .dir-viz-card--edges .dh-highlight
    // transform: scale(...) values in directors.css -- used below to size
    // node obstacles to their actual rendered (post-CSS-scale) footprint.
    var highlightScale = container.closest(".dir-viz-card--edges") ? 1.4 : 1.9;
    pinAndDeclutterLabels(svg, highlightSet, highlightScale);
  }

  var SVG_NS = "http://www.w3.org/2000/svg";

  var arrowMarkerCounter = 0;

  // Permanently reveals the title label for each of this director's own
  // (highlighted) films instead of requiring hover. Placement strategy,
  // cheapest option first:
  //   1. Try the label's native spot -- directly above (or, if that would
  //      clip the top edge, below) its own node, which is where
  //      src/cluster_ring_viz.py already positioned it. Keep it there,
  //      un-nudged and with no arrow, as long as it doesn't overlap any
  //      OTHER node in the graph (highlighted or dimmed) or any other
  //      pinned label.
  //   2. Otherwise, search a ring of candidate spots around the node at
  //      growing radii until one is fully clear of every node/label, move
  //      the label there, and draw an arrow from the node to it so it still
  //      reads as "this node's title" despite no longer sitting flush
  //      against it.
  //   3. If a cluster is dense enough that no candidate is ever fully
  //      clear (rare), fall back to whichever candidate overlaps the
  //      least, so a label is always shown rather than silently dropped.
  // Candidates are placed and locked in one at a time (each finalized
  // label becomes an obstacle for the next), so a title is never rendered
  // underneath another one, and never sits on top of an unrelated node.
  function pinAndDeclutterLabels(svg, highlightSet, highlightScale) {
    var viewBox = svg.viewBox.baseVal;
    var margin = 6;
    var minX = viewBox.x + margin;
    var minY = viewBox.y + margin;
    var maxX = viewBox.x + viewBox.width - margin;
    var maxY = viewBox.y + viewBox.height - margin;
    var firstLabelEl = svg.querySelector('[id^="t-"]');

    // Only the director's own (highlighted) nodes are no-cover obstacles --
    // covering a dimmed background node is fine, and treating all ~200-500
    // of them as obstacles was forcing labels far from their own node just
    // to dodge unrelated clutter, which is what was producing the long,
    // crisscrossing arrows. Keeping highlighted nodes as obstacles means a
    // label still won't land on top of a different one of this director's
    // own films. Inflated to each node's actual rendered size: highlighted
    // nodes are enlarged via CSS transform: scale(...), which getBBox() (SVG
    // user-space geometry) doesn't reflect on its own.
    var nodeObstacles = [];
    svg.querySelectorAll('[id^="n-"].dh-highlight, [id^="n-"] .dh-highlight').forEach(function (el) {
      var tconst = el.id ? el.id.slice(2) : el.closest('[id^="n-"]').id.slice(2);
      var polygon = el.tagName.toLowerCase() === "polygon" ? el : el.querySelector("polygon");
      if (!polygon) return;
      var box = polygon.getBBox();
      var cx = box.x + box.width / 2, cy = box.y + box.height / 2;
      var hw = (box.width / 2) * highlightScale + 2, hh = (box.height / 2) * highlightScale + 2;
      nodeObstacles.push({ tconst: tconst, x: cx - hw, y: cy - hh, w: hw * 2, h: hh * 2 });
    });
    // Band headers (e.g. "Hub (degree >= 20) -- 19 films") are as much a
    // no-cover target as any node -- a pinned label sitting on top of one
    // makes the ring's own count/threshold unreadable.
    svg.querySelectorAll(".ring-label").forEach(function (el) {
      var box = el.getBBox();
      if (box.width && box.height) {
        nodeObstacles.push({ tconst: null, x: box.x - 2, y: box.y - 2, w: box.width + 4, h: box.height + 4 });
      }
    });

    var pending = [];
    Object.keys(highlightSet).forEach(function (tconst) {
      var label = svg.querySelector("#" + CSS.escape("t-" + tconst));
      var nodeEl = svg.querySelector("#" + CSS.escape("n-" + tconst));
      if (!label || !nodeEl) return;
      label.classList.add("dh-label-pinned");

      var nodePolygon = nodeEl.tagName.toLowerCase() === "polygon" ? nodeEl : nodeEl.querySelector("polygon");
      var nodeBox = (nodePolygon || nodeEl).getBBox();
      var labelBox = label.getBBox();
      pending.push({
        tconst: tconst,
        label: label,
        x: labelBox.x, y: labelBox.y, w: labelBox.width, h: labelBox.height,
        nodeCx: nodeBox.x + nodeBox.width / 2,
        nodeCy: nodeBox.y + nodeBox.height / 2,
        nodeR: Math.max(nodeBox.width, nodeBox.height) / 2 * highlightScale
      });
    });
    if (!pending.length) return;

    // Top-to-bottom, left-to-right processing order keeps the cascade of
    // placed labels stable and deterministic across re-renders.
    pending.sort(function (a, b) { return (a.nodeCy - b.nodeCy) || (a.nodeCx - b.nodeCx); });

    function overlapArea(bx, by, bw, bh, o) {
      var ox = Math.max(0, Math.min(bx + bw, o.x + o.w) - Math.max(bx, o.x));
      var oy = Math.max(0, Math.min(by + bh, o.y + o.h) - Math.max(by, o.y));
      return ox * oy;
    }

    // No self-exclusion here, deliberately -- a label must clear its OWN
    // highlighted node too, not just other nodes. The native above/below
    // candidates below already reserve a gap past their own node's radius,
    // so they still pass; without this, only the fallback/grid-scan paths
    // (which don't know about that reserved gap) could land a label right
    // on top of the very node it's naming, hiding it.
    var placedBoxes = [];
    function totalOverlap(bx, by, bw, bh) {
      var total = 0;
      for (var i = 0; i < nodeObstacles.length; i++) {
        total += overlapArea(bx, by, bw, bh, nodeObstacles[i]);
        if (total > 0) return total; // any overlap disqualifies a candidate; exact area beyond that is irrelevant
      }
      for (var j = 0; j < placedBoxes.length; j++) {
        total += overlapArea(bx, by, bw, bh, placedBoxes[j]);
        if (total > 0) return total;
      }
      return total;
    }

    var leaders = document.createElementNS(SVG_NS, "g");
    leaders.setAttribute("class", "dh-leaders");
    var anyLeaders = false;
    var markerId = "dh-arrowhead-" + (arrowMarkerCounter++);

    pending.forEach(function (box) {
      var gap = 6;
      var aboveY = box.nodeCy - box.nodeR - gap - box.h;
      var belowY = box.nodeCy + box.nodeR + gap;
      var centeredX = box.nodeCx - box.w / 2;

      var candidates = [
        { x: centeredX, y: aboveY, leader: false },
        { x: centeredX, y: belowY, leader: false }
      ];
      // Ring of fallback candidates around the node at growing radii, each
      // needing an arrow since none sits flush above/below. Radius keeps
      // growing far past the immediate crowd (up to ~half the canvas) --
      // a director with a dozen+ films clustered in one small hub/mid band
      // can genuinely have no clear spot nearby, and a longer arrow into
      // open space reads far better than a label overlapping another one.
      var angleSteps = 16;
      for (var radiusStep = 1; radiusStep <= 40; radiusStep++) {
        var radius = box.nodeR + gap + radiusStep * (box.h * 0.8);
        for (var a = 0; a < angleSteps; a++) {
          var angle = (Math.PI * 2 * a) / angleSteps - Math.PI / 2;
          candidates.push({
            x: box.nodeCx + Math.cos(angle) * radius - box.w / 2,
            y: box.nodeCy + Math.sin(angle) * radius - box.h / 2,
            leader: true
          });
        }
      }

      var chosen = null, bestFallback = null, bestFallbackOverlap = Infinity;
      for (var i = 0; i < candidates.length; i++) {
        var c = candidates[i];
        var cx = Math.min(Math.max(c.x, minX), maxX - box.w);
        var cy = Math.min(Math.max(c.y, minY), maxY - box.h);
        var leader = c.leader || cx !== c.x || cy !== c.y;
        var overlap = totalOverlap(cx, cy, box.w, box.h);
        if (overlap === 0) {
          chosen = { x: cx, y: cy, leader: leader };
          break;
        }
        if (overlap < bestFallbackOverlap) {
          bestFallbackOverlap = overlap;
          bestFallback = { x: cx, y: cy, leader: true };
        }
      }
      // Last resort: the radial search around this node found nothing fully
      // clear (a wide label box can get funneled toward the same crowded
      // canvas edge as another one's search). Scan the whole card on a
      // coarse grid for any open rectangle before ever accepting an
      // overlapping placement -- picks the one closest to the node, so the
      // arrow stays as short as the actual free space allows.
      if (!chosen) {
        var gridStep = 18;
        var bestGrid = null, bestGridDist = Infinity;
        for (var gy = minY; gy <= maxY - box.h; gy += gridStep) {
          for (var gx = minX; gx <= maxX - box.w; gx += gridStep) {
            if (totalOverlap(gx, gy, box.w, box.h) === 0) {
              var ddx = gx + box.w / 2 - box.nodeCx, ddy = gy + box.h / 2 - box.nodeCy;
              var d = ddx * ddx + ddy * ddy;
              if (d < bestGridDist) { bestGridDist = d; bestGrid = { x: gx, y: gy }; }
            }
          }
        }
        if (bestGrid) chosen = { x: bestGrid.x, y: bestGrid.y, leader: true };
      }
      if (!chosen) chosen = bestFallback;

      var dx = chosen.x - box.x, dy = chosen.y - box.y;
      if (dx || dy) {
        box.label.setAttribute("transform", "translate(" + dx.toFixed(1) + "," + dy.toFixed(1) + ")");
      }
      placedBoxes.push({ x: chosen.x, y: chosen.y, w: box.w, h: box.h });

      // Always draw the arrow, even for a label sitting right at its native
      // above/below spot -- when two of this director's films have nearby
      // nodes, an un-arrowed label is genuinely ambiguous about which node
      // it names, so every label gets an explicit pointer to its own node.
      {
        var rx1 = chosen.x, ry1 = chosen.y, rx2 = rx1 + box.w, ry2 = ry1 + box.h;
        var targetX = Math.min(Math.max(box.nodeCx, rx1), rx2);
        var targetY = Math.min(Math.max(box.nodeCy, ry1), ry2);
        var line = document.createElementNS(SVG_NS, "line");
        line.setAttribute("class", "dh-leader");
        // Drawn label-end -> node-end (not node -> label) so the arrowhead
        // (marker-end) lands on the node -- the arrow should point at what
        // the label identifies, not back at the label itself.
        line.setAttribute("x1", targetX.toFixed(1));
        line.setAttribute("y1", targetY.toFixed(1));
        line.setAttribute("x2", box.nodeCx.toFixed(1));
        line.setAttribute("y2", box.nodeCy.toFixed(1));
        line.setAttribute("marker-end", "url(#" + markerId + ")");
        leaders.appendChild(line);
        anyLeaders = true;

        // The line itself becomes an obstacle too (padded thin rectangle
        // around its span), so a later label can't land on top of an
        // earlier one's leader/arrow.
        var linePad = 4;
        placedBoxes.push({
          x: Math.min(targetX, box.nodeCx) - linePad,
          y: Math.min(targetY, box.nodeCy) - linePad,
          w: Math.abs(targetX - box.nodeCx) + linePad * 2,
          h: Math.abs(targetY - box.nodeCy) + linePad * 2
        });
      }
    });

    if (anyLeaders) {
      var defs = document.createElementNS(SVG_NS, "defs");
      var marker = document.createElementNS(SVG_NS, "marker");
      marker.setAttribute("id", markerId);
      marker.setAttribute("markerWidth", "8");
      marker.setAttribute("markerHeight", "8");
      marker.setAttribute("refX", "6.5");
      marker.setAttribute("refY", "3.5");
      marker.setAttribute("orient", "auto-start-reverse");
      marker.setAttribute("markerUnits", "userSpaceOnUse");
      var arrowPath = document.createElementNS(SVG_NS, "path");
      arrowPath.setAttribute("d", "M 0 0 L 7 3.5 L 0 7 z");
      arrowPath.setAttribute("class", "dh-leader-arrowhead");
      marker.appendChild(arrowPath);
      defs.appendChild(marker);
      svg.insertBefore(defs, svg.firstChild);

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
