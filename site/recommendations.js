/*
 * "Find Your Film" survey engine: step-by-step question flow, a transparent
 * client-side weighted scorer over the real film records in
 * assets/films-data.js, and results rendering. No backend, no fetch() --
 * everything needed is already loaded as plain <script> globals so this
 * works from a file:// URL and under any GitHub Pages subpath.
 */

(function () {
  "use strict";

  var FILMS = window.FILMS || [];
  var MAX_DEGREE = window.FILMS_MAX_DEGREE || 1;

  // ---------------------------------------------------------------------
  // Survey definition
  // ---------------------------------------------------------------------

  var SURVEY_QUESTIONS = [
    {
      id: "mood",
      type: "single",
      prompt: "What kind of movie night are you looking for?",
      options: [
        { value: "comforting", label: "Something comforting" },
        { value: "exciting", label: "Something exciting" },
        { value: "emotional", label: "Something emotional" },
        { value: "mysterious", label: "Something mysterious" },
        { value: "funny", label: "Something funny" },
        { value: "challenging", label: "Something that will challenge me" },
        { value: "surprise", label: "Surprise me" },
      ],
    },
    {
      id: "genres",
      type: "multi",
      max: 3,
      prompt: "Which genres sound good right now?",
      hint: "Choose up to 3.",
      options: [
        { value: "drama", label: "Drama" },
        { value: "comedy", label: "Comedy" },
        { value: "romance", label: "Romance" },
        { value: "thriller_mystery", label: "Thriller or mystery" },
        { value: "crime", label: "Crime" },
        { value: "horror", label: "Horror" },
        { value: "scifi_fantasy", label: "Science fiction or fantasy" },
        { value: "documentary", label: "Documentary" },
        { value: "war_historical", label: "War or historical" },
        { value: "experimental", label: "Experimental" },
        { value: "no_preference", label: "No preference", exclusive: true },
      ],
    },
    {
      id: "pace",
      type: "single",
      prompt: "What pace are you in the mood for?",
      options: [
        { value: "slow_atmospheric", label: "Slow and atmospheric" },
        { value: "balanced", label: "Balanced" },
        { value: "fast_eventful", label: "Fast and eventful" },
        { value: "no_preference", label: "No preference" },
      ],
    },
    {
      id: "tone",
      type: "multi",
      max: 2,
      prompt: "Which tone sounds best?",
      hint: "Choose up to 2.",
      options: [
        { value: "warm_hopeful", label: "Warm and hopeful" },
        { value: "dark_intense", label: "Dark and intense" },
        { value: "thoughtful_reflective", label: "Thoughtful and reflective" },
        { value: "strange_surreal", label: "Strange and surreal" },
        { value: "fun_playful", label: "Fun and playful" },
        { value: "bittersweet", label: "Bittersweet" },
        { value: "no_preference", label: "No preference", exclusive: true },
      ],
    },
    {
      id: "era",
      type: "single",
      prompt: "How far back in film history would you like to go?",
      options: [
        { value: "pre1950", label: "Before 1950" },
        { value: "1950s_60s", label: "1950s–1960s" },
        { value: "1970s_80s", label: "1970s–1980s" },
        { value: "1990s_2000s", label: "1990s–2000s" },
        { value: "2010s_plus", label: "2010 or newer" },
        { value: "any", label: "Any era" },
      ],
    },
    {
      id: "language",
      type: "single",
      prompt: "Are you open to films that are not primarily in English?",
      options: [
        { value: "yes_absolutely", label: "Yes, absolutely" },
        { value: "sometimes", label: "Sometimes" },
        { value: "english_preferred", label: "English preferred" },
        { value: "no_preference", label: "No preference" },
      ],
    },
    {
      id: "runtime",
      type: "single",
      prompt: "How much time do you have?",
      options: [
        { value: "under_90", label: "Under 90 minutes" },
        { value: "90_120", label: "90–120 minutes" },
        { value: "over_120", label: "Over 2 hours is fine" },
        { value: "no_preference", label: "No preference" },
      ],
    },
    {
      id: "adventure",
      type: "single",
      prompt: "How adventurous are you feeling?",
      options: [
        { value: "accessible", label: "Give me something accessible" },
        { value: "slightly_outside", label: "A little outside my comfort zone" },
        { value: "unusual", label: "Show me something unusual" },
        { value: "boldest", label: "Give me the boldest choice" },
        { value: "no_preference", label: "No preference" },
      ],
    },
    {
      id: "likedFilms",
      type: "films",
      max: 3,
      prompt: "Choose up to 3 films you already enjoy.",
      hint: "Optional — this is our strongest signal, but feel free to skip it.",
      optional: true,
    },
  ];

  // ---------------------------------------------------------------------
  // State
  // ---------------------------------------------------------------------

  var answers = {};
  var stepIndex = 0; // index into SURVEY_QUESTIONS
  var view = "intro"; // 'intro' | 'survey' | 'results'
  var lastRecs = null;

  function resetAnswers() {
    answers = {
      mood: null,
      genres: [],
      pace: null,
      tone: [],
      era: null,
      language: null,
      runtime: null,
      adventure: null,
      likedFilms: [],
    };
    stepIndex = 0;
  }
  resetAnswers();

  // ---------------------------------------------------------------------
  // DOM refs
  // ---------------------------------------------------------------------

  var introEl = document.getElementById("recs-intro");
  var surveyEl = document.getElementById("recs-survey");
  var resultsEl = document.getElementById("recs-results");

  var startBtn = document.getElementById("recs-start-btn");
  var progressLabel = document.getElementById("recs-progress-label");
  var progressFill = document.getElementById("recs-progress-fill");
  var questionEl = document.getElementById("recs-question");
  var backBtn = document.getElementById("recs-back-btn");
  var skipBtn = document.getElementById("recs-skip-btn");
  var nextBtn = document.getElementById("recs-next-btn");
  var errorEl = document.getElementById("recs-error");
  var restartLink = document.getElementById("recs-restart-link");

  var summaryEl = document.getElementById("recs-summary");
  var bestEl = document.getElementById("recs-best");
  var othersEl = document.getElementById("recs-others");
  var tryAgainBtn = document.getElementById("recs-tryagain-btn");
  var adjustBtn = document.getElementById("recs-adjust-btn");
  var surpriseBtn = document.getElementById("recs-surprise-btn");

  // ---------------------------------------------------------------------
  // View switching
  // ---------------------------------------------------------------------

  function showView(name) {
    view = name;
    introEl.hidden = name !== "intro";
    surveyEl.hidden = name !== "survey";
    resultsEl.hidden = name !== "results";
    window.scrollTo(0, 0);
  }

  startBtn.addEventListener("click", function () {
    stepIndex = 0;
    showView("survey");
    renderQuestion();
  });

  restartLink.addEventListener("click", function () {
    resetAnswers();
    showView("intro");
  });

  // ---------------------------------------------------------------------
  // Question rendering
  // ---------------------------------------------------------------------

  function currentQuestion() {
    return SURVEY_QUESTIONS[stepIndex];
  }

  function clearError() {
    errorEl.hidden = true;
    errorEl.textContent = "";
  }

  function showError(msg) {
    errorEl.hidden = false;
    errorEl.textContent = msg;
  }

  function renderQuestion() {
    clearError();
    var q = currentQuestion();
    var total = SURVEY_QUESTIONS.length;
    progressLabel.textContent = "Question " + (stepIndex + 1) + " of " + total;
    progressFill.style.width = ((stepIndex) / (total - 1)) * 100 + "%";

    backBtn.disabled = stepIndex === 0;
    skipBtn.hidden = !q.optional;
    nextBtn.textContent = stepIndex === total - 1 ? "See My Results" : "Next";

    questionEl.innerHTML = "";

    var heading = document.createElement("h2");
    heading.className = "recs-question-prompt";
    heading.textContent = q.prompt;
    heading.tabIndex = -1;
    questionEl.appendChild(heading);

    if (q.hint) {
      var hint = document.createElement("p");
      hint.className = "recs-question-hint";
      hint.textContent = q.hint;
      questionEl.appendChild(hint);
    }

    if (q.type === "single" || q.type === "multi") {
      questionEl.appendChild(renderOptionGrid(q));
    } else if (q.type === "films") {
      questionEl.appendChild(renderFilmPicker(q));
    }

    heading.focus({ preventScroll: true });
  }

  function renderOptionGrid(q) {
    var grid = document.createElement("div");
    grid.className = "recs-options recs-options--" + q.type;
    grid.setAttribute("role", q.type === "single" ? "radiogroup" : "group");
    grid.setAttribute("aria-label", q.prompt);

    var current = answers[q.id];

    q.options.forEach(function (opt) {
      var id = "opt-" + q.id + "-" + opt.value;
      var label = document.createElement("label");
      label.className = "recs-option";
      label.setAttribute("for", id);

      var input = document.createElement("input");
      input.type = q.type === "single" ? "radio" : "checkbox";
      input.name = q.id;
      input.id = id;
      input.value = opt.value;
      input.className = "recs-option-input";

      if (q.type === "single") {
        input.checked = current === opt.value;
      } else {
        input.checked = Array.isArray(current) && current.indexOf(opt.value) !== -1;
      }

      input.addEventListener("focus", function () {
        label.classList.add("is-focused");
      });
      input.addEventListener("blur", function () {
        label.classList.remove("is-focused");
      });

      input.addEventListener("change", function () {
        clearError();
        if (q.type === "single") {
          answers[q.id] = opt.value;
          syncOptionStates(grid, q, opt.value);
        } else {
          handleMultiChange(q, grid, opt);
        }
      });

      var text = document.createElement("span");
      text.className = "recs-option-label";
      text.textContent = opt.label;

      label.appendChild(input);
      label.appendChild(text);
      grid.appendChild(label);
    });

    return grid;
  }

  function syncOptionStates(grid, q, selectedValue) {
    var labels = grid.querySelectorAll(".recs-option");
    labels.forEach(function (label) {
      var input = label.querySelector("input");
      var isSelected =
        q.type === "single"
          ? input.value === selectedValue
          : input.checked;
      label.classList.toggle("is-selected", isSelected);
    });
  }

  function handleMultiChange(q, grid, opt) {
    var current = answers[q.id].slice();

    if (opt.exclusive) {
      // "No preference" clears everything else and stands alone.
      current = current.indexOf(opt.value) !== -1 ? [] : [opt.value];
    } else {
      // Selecting a real option always clears any exclusive selection.
      current = current.filter(function (v) {
        var o = q.options.filter(function (o2) {
          return o2.value === v;
        })[0];
        return !(o && o.exclusive);
      });
      var idx = current.indexOf(opt.value);
      if (idx !== -1) {
        current.splice(idx, 1);
      } else {
        if (q.max && current.length >= q.max) {
          showError("You can choose up to " + q.max + ".");
          // revert the checkbox that just got checked past the limit
          var inputEl = grid.querySelector(
            'input[value="' + opt.value + '"]'
          );
          if (inputEl) inputEl.checked = false;
          return;
        }
        current.push(opt.value);
      }
    }

    answers[q.id] = current;

    // Re-sync all checkbox .checked states (exclusive-clearing above can
    // change more than the one the user clicked).
    var labels = grid.querySelectorAll(".recs-option");
    labels.forEach(function (label) {
      var input = label.querySelector("input");
      var isSelected = current.indexOf(input.value) !== -1;
      input.checked = isSelected;
      label.classList.toggle("is-selected", isSelected);
    });
  }

  function renderFilmPicker(q) {
    var wrap = document.createElement("div");
    wrap.className = "recs-film-picker";

    var searchWrap = document.createElement("div");
    searchWrap.className = "recs-film-search";
    var input = document.createElement("input");
    input.type = "search";
    input.placeholder = "Search titles…";
    input.className = "recs-film-search-input";
    input.setAttribute("aria-label", "Search for a film you enjoy");
    searchWrap.appendChild(input);
    wrap.appendChild(searchWrap);

    var resultsList = document.createElement("ul");
    resultsList.className = "recs-film-results";
    wrap.appendChild(resultsList);

    var chipsWrap = document.createElement("div");
    chipsWrap.className = "recs-film-chips";
    wrap.appendChild(chipsWrap);

    function renderChips() {
      chipsWrap.innerHTML = "";
      answers.likedFilms.forEach(function (tconst) {
        var film = filmByT(tconst);
        if (!film) return;
        var chip = document.createElement("span");
        chip.className = "recs-chip";
        var label = document.createElement("span");
        label.textContent = film.title + (film.year ? " (" + film.year + ")" : "");
        var remove = document.createElement("button");
        remove.type = "button";
        remove.className = "recs-chip-remove";
        remove.setAttribute("aria-label", "Remove " + film.title);
        remove.textContent = "×";
        remove.addEventListener("click", function () {
          answers.likedFilms = answers.likedFilms.filter(function (t) {
            return t !== tconst;
          });
          renderChips();
          renderResultsList(input.value);
        });
        chip.appendChild(label);
        chip.appendChild(remove);
        chipsWrap.appendChild(chip);
      });
    }

    function renderResultsList(query) {
      resultsList.innerHTML = "";
      var trimmed = query.trim().toLowerCase();
      if (!trimmed) return;

      var matches = FILMS.filter(function (f) {
        return (
          f.title.toLowerCase().indexOf(trimmed) !== -1 &&
          answers.likedFilms.indexOf(f.t) === -1
        );
      }).slice(0, 25);

      if (matches.length === 0) {
        var empty = document.createElement("li");
        empty.className = "recs-film-result recs-film-result--empty";
        empty.textContent = "No titles match “" + query + "”.";
        resultsList.appendChild(empty);
        return;
      }

      matches.forEach(function (f) {
        var item = document.createElement("li");
        var btn = document.createElement("button");
        btn.type = "button";
        btn.className = "recs-film-result";
        btn.innerHTML =
          '<span class="recs-film-result-title">' +
          escapeHtml(f.title) +
          "</span>" +
          '<span class="recs-film-result-meta">' +
          escapeHtml([f.year, f.director].filter(Boolean).join(" · ")) +
          "</span>";
        btn.addEventListener("click", function () {
          if (answers.likedFilms.length >= q.max) {
            showError("You can choose up to " + q.max + " films.");
            return;
          }
          clearError();
          answers.likedFilms.push(f.t);
          renderChips();
          renderResultsList(input.value);
        });
        item.appendChild(btn);
        resultsList.appendChild(item);
      });
    }

    input.addEventListener("input", function () {
      renderResultsList(input.value);
    });

    renderChips();
    return wrap;
  }

  function filmByT(t) {
    for (var i = 0; i < FILMS.length; i++) {
      if (FILMS[i].t === t) return FILMS[i];
    }
    return null;
  }

  function escapeHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return (
        { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[
          c
        ] || c
      );
    });
  }

  // ---------------------------------------------------------------------
  // Navigation
  // ---------------------------------------------------------------------

  function validateCurrent() {
    var q = currentQuestion();
    if (q.optional) return true;
    if (q.type === "single") {
      if (!answers[q.id]) {
        showError("Please choose an option to continue.");
        return false;
      }
    } else if (q.type === "multi") {
      if (!answers[q.id] || answers[q.id].length === 0) {
        showError("Please choose at least one option to continue.");
        return false;
      }
    }
    return true;
  }

  nextBtn.addEventListener("click", function () {
    if (!validateCurrent()) return;
    if (stepIndex === SURVEY_QUESTIONS.length - 1) {
      submitSurvey();
    } else {
      stepIndex += 1;
      renderQuestion();
    }
  });

  backBtn.addEventListener("click", function () {
    if (stepIndex === 0) return;
    stepIndex -= 1;
    renderQuestion();
  });

  skipBtn.addEventListener("click", function () {
    clearError();
    if (stepIndex === SURVEY_QUESTIONS.length - 1) {
      submitSurvey();
    } else {
      stepIndex += 1;
      renderQuestion();
    }
  });

  surveyEl.addEventListener("keydown", function (e) {
    if (e.key !== "Enter") return;
    var tag = (e.target.tagName || "").toLowerCase();
    if (tag === "input" && e.target.type === "search") return;
    e.preventDefault();
    nextBtn.click();
  });

  function submitSurvey() {
    lastRecs = generateRecommendations(answers);
    renderResults(lastRecs, answers);
    showView("results");
  }

  adjustBtn.addEventListener("click", function () {
    stepIndex = 0;
    showView("survey");
    renderQuestion();
  });

  tryAgainBtn.addEventListener("click", function () {
    lastRecs = generateRecommendations(answers);
    renderResults(lastRecs, answers);
  });

  surpriseBtn.addEventListener("click", function () {
    if (!lastRecs) return;
    var wildcard = pickWildcard(lastRecs, answers);
    if (wildcard) {
      lastRecs = {
        best: wildcard,
        others: lastRecs.others,
        pool: lastRecs.pool,
      };
      renderResults(lastRecs, answers, { wildcard: true });
    }
  });

  // ---------------------------------------------------------------------
  // Scoring
  // ---------------------------------------------------------------------

  function clusterSizes() {
    var sizes = {};
    FILMS.forEach(function (f) {
      sizes[f.cluster] = (sizes[f.cluster] || 0) + 1;
    });
    return sizes;
  }

  function medianClusterSize(sizes) {
    var vals = Object.keys(sizes)
      .map(function (k) {
        return sizes[k];
      })
      .sort(function (a, b) {
        return a - b;
      });
    if (vals.length === 0) return 0;
    var mid = Math.floor(vals.length / 2);
    return vals.length % 2 ? vals[mid] : (vals[mid - 1] + vals[mid]) / 2;
  }

  function inEraRange(year, rangeKey) {
    if (!rangeKey || rangeKey === "any") return true;
    var range = ERA_RANGES[rangeKey];
    if (!range || year == null) return true;
    if (range[0] != null && year < range[0]) return false;
    if (range[1] != null && year > range[1]) return false;
    return true;
  }

  function inRuntimeRange(runtime, rangeKey) {
    if (!rangeKey || rangeKey === "no_preference") return true;
    var range = RUNTIME_RANGES[rangeKey];
    if (!range || runtime == null) return true;
    if (range[0] != null && runtime < range[0]) return false;
    if (range[1] != null && runtime > range[1]) return false;
    return true;
  }

  function buildCandidatePool(ans) {
    var likedSet = {};
    ans.likedFilms.forEach(function (t) {
      likedSet[t] = true;
    });

    var all = FILMS.filter(function (f) {
      return !likedSet[f.t];
    });

    var pool = all;
    if (ans.era) {
      var eraFiltered = all.filter(function (f) {
        return inEraRange(f.year, ans.era);
      });
      if (eraFiltered.length >= 5) pool = eraFiltered;
    }
    if (ans.runtime) {
      var runtimeFiltered = pool.filter(function (f) {
        return inRuntimeRange(f.runtime, ans.runtime);
      });
      if (runtimeFiltered.length >= 5) pool = runtimeFiltered;
    }
    return pool;
  }

  function genreWeightSum(filmGenres, weightMap) {
    if (!filmGenres || !weightMap) return 0;
    var sum = 0;
    filmGenres.forEach(function (g) {
      if (weightMap[g]) sum += weightMap[g];
    });
    return sum;
  }

  function scoreFilm(film, ans, sizes, medianSize, likedFilmObjs, rng) {
    var reasons = []; // { text, weight }
    var score = 0;

    // 1. Similarity to selected films -- highest-weighted signal.
    if (likedFilmObjs.length > 0) {
      likedFilmObjs.forEach(function (liked) {
        var neighborHit = (liked.neighbors || []).filter(function (n) {
          return n.t === film.t;
        })[0];
        if (neighborHit) {
          var bonus = Math.min(30, neighborHit.shared * 12);
          score += bonus;
          reasons.push({
            text: "a shared-cast connection with “" + liked.title + "”",
            weight: bonus,
          });
        }
        if (liked.cluster && liked.cluster === film.cluster) {
          score += 14;
          reasons.push({
            text: "the same " + film.clusterName + " cluster as “" + liked.title + "”",
            weight: 14,
          });
        }
        if (liked.director && liked.director === film.director) {
          score += 20;
          reasons.push({
            text: "being directed by " + film.director + ", like “" + liked.title + "”",
            weight: 20,
          });
        }
        var sharedGenres = (film.genres || []).filter(function (g) {
          return (liked.genres || []).indexOf(g) !== -1;
        });
        if (sharedGenres.length) {
          var gBonus = sharedGenres.length * 4;
          score += gBonus;
          reasons.push({
            text: "genre overlap with “" + liked.title + "”",
            weight: gBonus,
          });
        }
        if (liked.country && liked.country === film.country) {
          score += 4;
        }
        if (liked.year && film.year && Math.abs(liked.year - film.year) <= 10) {
          score += 3;
        }
      });
    }

    // 2. Mood, tone, and genre matches.
    if (ans.mood && MOOD_TO_GENRE_WEIGHTS[ans.mood]) {
      var moodBonus = genreWeightSum(film.genres, MOOD_TO_GENRE_WEIGHTS[ans.mood]) * 4;
      if (moodBonus > 0) {
        score += moodBonus;
        reasons.push({ text: "your mood for " + moodLabel(ans.mood), weight: moodBonus });
      }
    }

    var selectedGenres = (ans.genres || []).filter(function (g) {
      return g !== "no_preference";
    });
    if (selectedGenres.length) {
      var matchedLabels = [];
      var genreBonus = 0;
      selectedGenres.forEach(function (gKey) {
        var tags = GENRE_OPTION_TO_IMDB[gKey] || [];
        var hit = (film.genres || []).some(function (g) {
          return tags.indexOf(g) !== -1;
        });
        if (hit) {
          genreBonus += 10;
          matchedLabels.push(genreLabel(gKey));
        } else if (gKey === "experimental" && EXPERIMENTAL_AFFINITY_CLUSTERS.has(film.cluster)) {
          genreBonus += 8;
          matchedLabels.push("experimental, arthouse-leaning cinema");
        }
      });
      if (genreBonus > 0) {
        score += genreBonus;
        reasons.push({
          text: matchedLabels.slice(0, 2).join(" and ") + " storytelling",
          weight: genreBonus,
        });
      }
    }

    var selectedTones = (ans.tone || []).filter(function (t) {
      return t !== "no_preference";
    });
    if (selectedTones.length) {
      var toneBonus = 0;
      selectedTones.forEach(function (tKey) {
        toneBonus += genreWeightSum(film.genres, TONE_TO_GENRE_WEIGHTS[tKey]) * 3;
        if (ADVENTUROUS_TONES.has(tKey) && EXPERIMENTAL_AFFINITY_CLUSTERS.has(film.cluster)) {
          toneBonus += 6;
        }
      });
      if (toneBonus > 0) {
        score += toneBonus;
        reasons.push({ text: "a " + toneLabel(selectedTones[0]) + " tone", weight: toneBonus });
      }
    }

    if (ans.mood && ADVENTUROUS_MOODS.has(ans.mood) && EXPERIMENTAL_AFFINITY_CLUSTERS.has(film.cluster)) {
      score += 5;
    }

    // Pace lean (soft; runtime question is the hard-ish signal).
    if (ans.pace && PACE_PROFILES[ans.pace]) {
      var paceBonus = genreWeightSum(film.genres, PACE_PROFILES[ans.pace].genreWeights) * 2;
      score += paceBonus;
    }

    // 3. Era & runtime preference (bonus on top of the filter already
    // applied when the candidate pool was built).
    if (ans.era && ans.era !== "any" && inEraRange(film.year, ans.era)) {
      score += 12;
      reasons.push({ text: eraLabel(ans.era) + " filmmaking", weight: 12 });
    }
    if (ans.runtime && ans.runtime !== "no_preference" && inRuntimeRange(film.runtime, ans.runtime)) {
      score += 8;
    }

    // 4. Language preference.
    if (ans.language && LANGUAGE_WEIGHTS[ans.language] && film.englishSpeaking != null) {
      var lw = LANGUAGE_WEIGHTS[ans.language];
      if (film.englishSpeaking) {
        score += lw.englishBonus;
      } else {
        score += lw.nonEnglishBonus;
        if (lw.nonEnglishBonus > 5) {
          reasons.push({ text: "international cinema", weight: lw.nonEnglishBonus });
        }
      }
    }

    // 5. Adventurousness / accessibility.
    if (ans.adventure && ADVENTURE_PROFILES[ans.adventure]) {
      var prof = ADVENTURE_PROFILES[ans.adventure];
      var normDegree = MAX_DEGREE ? film.degree / MAX_DEGREE : 0;
      var niche = (sizes[film.cluster] || 0) < medianSize ? 1 : 0;
      var advBonus =
        prof.degreeWeight * normDegree +
        prof.nicheWeight * niche +
        (film.englishSpeaking ? prof.englishBias : 0);
      score += advBonus;
      if (niche && (ans.adventure === "unusual" || ans.adventure === "boldest")) {
        reasons.push({ text: "an unusual, off-the-beaten-path pick", weight: prof.nicheWeight });
      } else if (!niche && ans.adventure === "accessible") {
        reasons.push({ text: "an accessible, well-connected classic", weight: prof.degreeWeight * normDegree });
      }
    }

    // Controlled variety: small random jitter so identical answers don't
    // always produce an identical order, without ever outweighing a real
    // preference match.
    score += (rng() - 0.5) * 6;

    reasons.sort(function (a, b) {
      return b.weight - a.weight;
    });

    return { film: film, score: score, reasons: reasons };
  }

  function moodLabel(key) {
    var q = SURVEY_QUESTIONS[0];
    var o = q.options.filter(function (o) {
      return o.value === key;
    })[0];
    return o ? o.label.toLowerCase() : key;
  }
  function genreLabel(key) {
    var q = SURVEY_QUESTIONS[1];
    var o = q.options.filter(function (o) {
      return o.value === key;
    })[0];
    return o ? o.label.toLowerCase() : key;
  }
  function toneLabel(key) {
    var q = SURVEY_QUESTIONS[3];
    var o = q.options.filter(function (o) {
      return o.value === key;
    })[0];
    return o ? o.label.toLowerCase() : key;
  }
  function eraLabel(key) {
    var q = SURVEY_QUESTIONS[4];
    var o = q.options.filter(function (o) {
      return o.value === key;
    })[0];
    return o ? o.label.toLowerCase() : key;
  }

  function mulberry32(seed) {
    return function () {
      seed |= 0;
      seed = (seed + 0x6d2b79f5) | 0;
      var t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  function generateRecommendations(ans) {
    var sizes = clusterSizes();
    var medianSize = medianClusterSize(sizes);
    var likedFilmObjs = (ans.likedFilms || [])
      .map(filmByT)
      .filter(Boolean);

    var pool = buildCandidatePool(ans);
    var rng = mulberry32(Date.now() & 0xffffffff);

    var scored = pool.map(function (f) {
      return scoreFilm(f, ans, sizes, medianSize, likedFilmObjs, rng);
    });

    scored.sort(function (a, b) {
      return b.score - a.score;
    });

    return {
      best: scored[0],
      others: scored.slice(1, 5),
      pool: scored,
    };
  }

  function pickWildcard(recs, ans) {
    var pool = recs.pool || [];
    var usedT = {};
    if (recs.best) usedT[recs.best.film.t] = true;
    recs.others.forEach(function (r) {
      usedT[r.film.t] = true;
    });
    var candidates = pool.filter(function (r) {
      return !usedT[r.film.t];
    });
    if (!candidates.length) return recs.best;
    // Weight toward the upper-middle of the remaining pool -- a real
    // curveball, but still drawn from films that already passed the
    // era/runtime filters, so it can't strongly conflict with the answers.
    var band = candidates.slice(0, Math.max(10, Math.min(40, candidates.length)));
    var pick = band[Math.floor(Math.random() * band.length)];
    pick.reasons = [{ text: "a wildcard pick from outside your top matches", weight: 99 }].concat(
      pick.reasons
    );
    return pick;
  }

  // ---------------------------------------------------------------------
  // Results rendering
  // ---------------------------------------------------------------------

  function explanationSentence(reasons) {
    var top = reasons.slice(0, 3).map(function (r) {
      return r.text;
    });
    if (top.length === 0) {
      return "A pick from the collection that fits the shape of what you're after.";
    }
    var joined;
    if (top.length === 1) {
      joined = top[0];
    } else if (top.length === 2) {
      joined = top[0] + " and " + top[1];
    } else {
      joined = top[0] + ", " + top[1] + ", and " + top[2];
    }
    return "A strong match for your interest in " + joined + ".";
  }

  function filmDestinations(film) {
    var dests = [];
    if (film.criterionUrl) {
      dests.push({ href: film.criterionUrl, label: "View on Criterion" });
    }
    if (film.channelUrl) {
      dests.push({ href: film.channelUrl, label: "Watch on the Criterion Channel" });
    }
    // Neither Criterion page was captured in this project's data for every
    // title -- every film record does carry its IMDb tconst though, so that
    // makes a reliable fallback rather than a guessed/invented URL.
    if (!film.criterionUrl && !film.channelUrl) {
      dests.push({ href: "https://www.imdb.com/title/" + film.t + "/", label: "View on IMDb" });
    }
    dests.push({ href: clusterHref(film.cluster), label: "Explore the " + film.clusterName + " cluster" });
    return dests;
  }

  function clusterHref(clusterId) {
    return "clusters/" + clusterId + ".html";
  }

  function metaLine(film) {
    var parts = [];
    if (film.director) parts.push(film.director);
    if (film.runtime) parts.push(film.runtime + " min");
    if (film.country) parts.push(film.country);
    return parts.join(" · ");
  }

  function filmCardMarkup(scored, opts) {
    opts = opts || {};
    var film = scored.film;
    var dests = filmDestinations(film);
    var badge = opts.wildcard
      ? '<span class="recs-card-badge recs-card-badge--wildcard">Wildcard</span>'
      : opts.best
      ? '<span class="recs-card-badge">Best Match</span>'
      : "";

    return (
      '<article class="recs-card' + (opts.best ? " recs-card--best" : "") + '">' +
      '<div class="recs-card-swatch" style="background:' +
      film.color +
      '">' +
      badge +
      '<span class="recs-card-cluster">' +
      escapeHtml(film.clusterName) +
      "</span>" +
      "</div>" +
      '<div class="recs-card-body">' +
      "<h3>" +
      escapeHtml(film.title) +
      (film.year ? ' <span class="recs-card-year">(' + film.year + ")</span>" : "") +
      "</h3>" +
      '<p class="recs-card-meta">' +
      escapeHtml(metaLine(film)) +
      "</p>" +
      '<p class="recs-card-why">' +
      escapeHtml(explanationSentence(scored.reasons)) +
      "</p>" +
      '<div class="recs-card-links">' +
      dests
        .map(function (dest) {
          return (
            '<a class="recs-card-link" href="' +
            escapeHtml(dest.href) +
            '" target="_blank" rel="noopener noreferrer">' +
            escapeHtml(dest.label) +
            " →</a>"
          );
        })
        .join("") +
      "</div>" +
      "</div>" +
      "</article>"
    );
  }

  function answerSummaryMarkup(ans) {
    var bits = [];
    if (ans.mood) bits.push(labelFor(0, ans.mood));
    if (ans.genres && ans.genres.length) {
      bits.push(
        ans.genres
          .filter(function (g) {
            return g !== "no_preference";
          })
          .map(function (g) {
            return labelFor(1, g);
          })
          .join(", ") || "no genre preference"
      );
    }
    if (ans.pace) bits.push(labelFor(2, ans.pace));
    if (ans.era) bits.push(labelFor(4, ans.era));
    if (ans.runtime) bits.push(labelFor(6, ans.runtime));
    if (ans.likedFilms && ans.likedFilms.length) {
      var titles = ans.likedFilms
        .map(filmByT)
        .filter(Boolean)
        .map(function (f) {
          return f.title;
        });
      if (titles.length) bits.push("inspired by " + titles.join(", "));
    }
    return bits
      .filter(Boolean)
      .map(function (b) {
        return '<span class="recs-summary-chip">' + escapeHtml(b) + "</span>";
      })
      .join("");
  }

  function labelFor(qIndex, value) {
    var q = SURVEY_QUESTIONS[qIndex];
    var o = q.options.filter(function (o) {
      return o.value === value;
    })[0];
    return o ? o.label : value;
  }

  function renderResults(recs, ans, opts) {
    opts = opts || {};
    summaryEl.innerHTML = answerSummaryMarkup(ans);

    if (!recs.best) {
      bestEl.innerHTML =
        '<p class="recs-empty">We couldn’t find a confident match — try loosening an answer or two.</p>';
      othersEl.innerHTML = "";
      return;
    }

    bestEl.innerHTML = filmCardMarkup(recs.best, { best: !opts.wildcard, wildcard: !!opts.wildcard });
    othersEl.innerHTML = recs.others
      .map(function (r) {
        return filmCardMarkup(r, {});
      })
      .join("");
  }

  // ---------------------------------------------------------------------
  // Init
  // ---------------------------------------------------------------------

  showView("intro");
})();
