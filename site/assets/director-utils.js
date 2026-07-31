// Shared helpers for the "Explore Directors by Cluster" tab and director
// profile pages. Derives the director -> film -> cluster index at runtime
// from window.FILMS (site/assets/films-data.js), the same authoritative,
// already-generated dataset the rest of the site (recommendations, hex
// grid) is built from. No director-to-film relationships are hand-entered
// anywhere -- they're all computed from that one source below.
(function (global) {
  "use strict";

  // Which physical SVG asset backs each cluster's node-network visualization
  // on its site/clusters/<id>.html page (see site/clusters/*.html "object
  // data=" attributes). hiddenGems has no node visualization -- its
  // cluster page is a text-only small-cluster analysis, not a network.
  var CLUSTER_VIZ_SVG = {
    anglophone_classic: "anglophone_classic_rings.svg",
    bergman_scandinavian: "bergman_scandinavian_rings.svg",
    czech_new_wave: "czech_new_wave_graph.svg",
    european_art_cinema: "european_art_cinema_rings.svg",
    hong_kong_taiwan_cinema: "hong_kong_taiwan_cinema_rings.svg",
    japanese_cinema: "japanese_cinema_rings.svg",
    satyajit_ray_indian: "satyajit_ray_indian_graph.svg",
    soviet_cinema: "soviet_cinema_graph.svg",
    transatlantic_auteur_cinema: "transatlantic_auteur_cinema_rings.svg",
    youssef_chahine_egyptian: "youssef_chahine_egyptian_graph.svg",
    hiddenGems: null
  };

  // site/clusters/<id>.html page for each cluster (for "view full cluster" links).
  var CLUSTER_PAGE = {
    anglophone_classic: "clusters/anglophone_classic.html",
    bergman_scandinavian: "clusters/bergman_scandinavian.html",
    czech_new_wave: "clusters/czech_new_wave.html",
    european_art_cinema: "clusters/european_art_cinema.html",
    hong_kong_taiwan_cinema: "clusters/hong_kong_taiwan_cinema.html",
    japanese_cinema: "clusters/japanese_cinema.html",
    satyajit_ray_indian: "clusters/satyajit_ray_indian.html",
    soviet_cinema: "clusters/soviet_cinema.html",
    transatlantic_auteur_cinema: "clusters/transatlantic_auteur_cinema.html",
    youssef_chahine_egyptian: "clusters/youssef_chahine_egyptian.html",
    hiddenGems: "clusters/hiddenGems.html"
  };

  // Unicode combining-diacritical-marks block (U+0300-U+036F), written as
  // \u escapes so it survives editing/copying intact.
  var COMBINING_MARKS_RE = new RegExp("[\\u0300-\\u036f]", "g");

  function stripDiacritics(s) {
    return String(s).normalize("NFKD").replace(COMBINING_MARKS_RE, "");
  }

  // "Lois Weber and Phillips Smalley" / "A, B, and C" / "X and X" (dup) ->
  // ["Lois Weber", "Phillips Smalley"]. Splits on commas and " and ",
  // trims, and drops exact-duplicate names within the same credit.
  function splitDirectors(raw) {
    if (!raw) return [];
    var normalized = String(raw).replace(/\s*,?\s+and\s+/gi, ", ");
    var seen = Object.create(null);
    var out = [];
    normalized.split(",").forEach(function (part) {
      var name = part.trim();
      if (name && !seen[name]) {
        seen[name] = true;
        out.push(name);
      }
    });
    return out;
  }

  // Stable, URL-safe id: strip diacritics, lowercase, drop apostrophes/
  // periods, collapse everything else to hyphens. Two spellings of the same
  // name (e.g. "Karel Kachyna" with/without the caron) intentionally
  // collapse to the same slug so that director gets one profile, not two.
  function slugify(name) {
    var n = stripDiacritics(name).toLowerCase();
    n = n.replace(/['’.]/g, "");
    n = n.replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
    return n || "unknown";
  }

  // Diacritic-insensitive fold, used for forgiving search matching.
  function foldForSearch(s) {
    return stripDiacritics(s).toLowerCase();
  }

  // Prefer the spelling that carries diacritics (more complete / correct)
  // when two records for the same slug disagree; falls back to whichever
  // sorts first for determinism.
  function betterName(a, b) {
    if (a === b) return a;
    var aHasDiacritic = stripDiacritics(a) !== a;
    var bHasDiacritic = stripDiacritics(b) !== b;
    if (aHasDiacritic && !bHasDiacritic) return a;
    if (bHasDiacritic && !aHasDiacritic) return b;
    return a.localeCompare(b) <= 0 ? a : b;
  }

  // Builds the full index from window.FILMS:
  //   directors: { slug: { slug, name, filmsByCluster: {clusterId: [tconst,...]}, tconsts: [...] } }
  //   clusters: [{ id, name, color, directorSlugs: [slug,...] (alpha) }, ...] sorted by film count desc
  function buildIndex(films) {
    var directors = Object.create(null);
    var clusterMeta = Object.create(null);

    films.forEach(function (f) {
      if (!clusterMeta[f.cluster]) {
        clusterMeta[f.cluster] = {
          id: f.cluster,
          name: f.clusterName,
          color: f.color,
          filmCount: 0,
          directorSlugSet: Object.create(null)
        };
      }
      clusterMeta[f.cluster].filmCount++;

      splitDirectors(f.director).forEach(function (name) {
        var slug = slugify(name);
        if (!directors[slug]) {
          directors[slug] = { slug: slug, name: name, filmsByCluster: Object.create(null), tconsts: [] };
        } else {
          directors[slug].name = betterName(directors[slug].name, name);
        }
        var d = directors[slug];
        if (!d.filmsByCluster[f.cluster]) d.filmsByCluster[f.cluster] = [];
        if (d.filmsByCluster[f.cluster].indexOf(f.t) === -1) {
          d.filmsByCluster[f.cluster].push(f.t);
          d.tconsts.push(f.t);
        }
        clusterMeta[f.cluster].directorSlugSet[slug] = true;
      });
    });

    var clusters = Object.keys(clusterMeta)
      .map(function (id) {
        var m = clusterMeta[id];
        var slugs = Object.keys(m.directorSlugSet).sort(function (a, b) {
          return directors[a].name.localeCompare(directors[b].name, undefined, { sensitivity: "base" });
        });
        return {
          id: m.id,
          name: m.name,
          color: m.color,
          filmCount: m.filmCount,
          directorSlugs: slugs,
          vizSvg: CLUSTER_VIZ_SVG[id] || null,
          page: CLUSTER_PAGE[id] || null
        };
      })
      .sort(function (a, b) { return b.filmCount - a.filmCount; });

    return { directors: directors, clusters: clusters };
  }

  function filmsByTconst(films) {
    var map = Object.create(null);
    films.forEach(function (f) { map[f.t] = f; });
    return map;
  }

  global.DirectorUtils = {
    splitDirectors: splitDirectors,
    slugify: slugify,
    foldForSearch: foldForSearch,
    buildIndex: buildIndex,
    filmsByTconst: filmsByTconst,
    CLUSTER_VIZ_SVG: CLUSTER_VIZ_SVG,
    CLUSTER_PAGE: CLUSTER_PAGE
  };
})(window);
