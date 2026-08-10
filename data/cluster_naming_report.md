# Cluster naming report -- 2026-07-31 Best Picture nominee import

Louvain community detection on the shared-actor graph after merging the 619
Best Picture nominee films into the canonical dataset (591 genuinely new;
28 already present as Criterion titles). Graph: 2,170 nodes (films with at
least one shared-actor edge), 18,799 edges. `run_louvain(random_state=42)`;
confirmed byte-identical across two consecutive runs (see
`output/clustering_run_manifest.json`).

Raw Louvain produced 47 communities. Communities with fewer than
`MIN_NAMED_CLUSTER_SIZE = 15` films (36 of the 47, 103 films total) are
merged into `hiddenGems`, along with the 167 films that have no
shared-actor edge at all (no cast data, or cast shared with nobody else in
the collection). See `src/cluster.py`'s module docstring for why 15 was
chosen: it matches this project's own historical floor for a named cluster
(satyajit_ray_indian/soviet_cinema/youssef_chahine_egyptian previously sat
at 17-24 films) rather than being picked to reproduce the old cluster count.

11 communities clear the floor and get names below. Field definitions match
the design doc: machine cluster ID (stable, used as slug/URL/DOM id/object
key), display name, film count, dominant evidence, representative films,
alternatives considered, selection reason, confidence.

---

## modern_american_cinema (community 0)
**Display name:** Modern American Cinema
**Films:** 498 (23.0% of clustered films)
**Evidence:** Years 1954-2025, median 1997. Top genres: Drama (439),
Comedy (120), Crime (97), Biography (92), Romance (90). Top directors:
Steven Spielberg (14), Martin Scorsese (11), Jim Jarmusch (7), Clint
Eastwood (5), John Cassavetes (5), David Lynch (5). Internal/external edge
ratio 0.81.
**Representative films:** The Departed, The Grand Budapest Hotel, Don't
Look Up, Nightmare Alley, Killers of the Flower Moon.
**Alternatives considered:** "American Prestige Cinema" (rejected -- genre
mix includes plenty of non-prestige comedy/crime, and "prestige" reads as
Oscar-only when this is a mainstream+arthouse mix); "American Auteur
Cinema" (rejected -- misleadingly implies a Cassavetes/Jarmusch identity
when Spielberg/Eastwood mainstream films dominate by raw count).
**Selection reason:** No single director or sub-genre dominates; the
strongest, most defensible signal is nationality + a contemporary-leaning
median year. This is overwhelmingly the landing zone for the new Best
Picture nominees plus this project's existing American independent/auteur
Criterion titles, which the shared-actor graph merged into one community.
**Confidence:** Medium -- large and genre-heterogeneous by nature; the name
describes the real center of mass but individual films vary widely.

## european_art_cinema (community 4)
**Display name:** European Art Cinema
**Films:** 477 (22.0%)
**Evidence:** Years 1916-2024, median 1970. Top genres: Drama (410),
Comedy (151), Romance (145). Top directors: Rainer Werner Fassbinder (19),
Youssef Chahine (18), François Truffaut (12), Carlos Saura (12), Bertrand
Tavernier (11), Jacques Rivette (10). Internal/external ratio 0.86.
**Representative films:** La nuit de Varennes, Mr. Klein, One Hundred and
One Nights, The Phantom of Liberty, The Last Metro.
**Alternatives considered:** "French New Wave & Beyond" (rejected --
directors span France/Germany/Egypt/Spain, not France alone).
**Selection reason:** Same identity as this project's pre-import
`european_art_cinema` cluster, independently re-earned: still the
best-supported label for a continental-European, director-driven arthouse
community with no single dominant nationality.
**Confidence:** High -- large, high internal cohesion, consistent directors
across multiple European countries.

## golden_age_hollywood_british (community 7)
**Display name:** Golden Age Hollywood & British Cinema
**Films:** 467 (21.5%)
**Evidence:** Years 1913-2015, median 1946. Top genres: Drama (380),
Romance (161), Comedy (115), Adventure (63). Top directors: David Lean
(13), William Wyler (13), John Ford (10), Alfred Hitchcock (10), George
Stevens (8), Frank Capra (7). Internal/external ratio 0.85.
**Representative films:** Doctor Zhivago, Mr. Smith Goes to Washington,
Wuthering Heights, It's a Wonderful Life, Lawrence of Arabia, Rebecca.
**Alternatives considered:** "Anglophone Classic" (the old name -- rejected
per the instruction not to reuse old names automatically; also less
specific than what the evidence actually shows, which is a *studio-era*
identity, not just English-language).
**Selection reason:** Median year and every top director point to
1930s-1960s Hollywood/British studio filmmaking; this absorbed the old
anglophone_classic cluster plus the many classic-era Best Picture winners
newly added (Wuthering Heights, Mr. Smith Goes to Washington, Rebecca,
etc.), which reinforced rather than diluted the identity.
**Confidence:** High -- large, coherent director list, all studio-era
Hollywood/British.

## classic_japanese_cinema (community 13)
**Display name:** Classic Japanese Cinema
**Films:** 216 (10.0%)
**Evidence:** Years 1929-1998, median 1956. Top genres: Drama (171), Action
(36), Comedy (35). Top directors: Keisuke Kinoshita (35), Yasujiro Ozu
(32), Akira Kurosawa (22), Ishiro Honda (16), Mikio Naruse (15), Masaki
Kobayashi (12). Internal/external ratio 0.82.
**Representative films:** The Bad Sleep Well, Equinox Flower, The Munekata
Sisters, An Autumn Afternoon, Flowing.
**Alternatives considered:** "Japanese Cinema" (the old, unqualified name --
rejected because this run split Japan into two distinct communities, see
japanese_new_wave_genre below, so an unqualified name would be ambiguous
between them).
**Selection reason:** Ozu/Naruse/Kinoshita-led studio and shomin-geki
(everyday family drama) tradition, median 1956 -- distinct in era and genre
mix from the separate genre/New-Wave Japanese community.
**Confidence:** High -- large, single-nationality, consistent directors and
genre profile.

## japanese_new_wave_genre (community 3)
**Display name:** Japanese New Wave & Genre Cinema
**Films:** 142 (6.5%)
**Evidence:** Years 1937-2008, median 1968. Top genres: Drama (117), Action
(57), Crime (33), Adventure (31). Top directors: Kenji Misumi (13), Nagisa
Oshima (13), Masahiro Shinoda (12), Juzo Itami (9), Seijun Suzuki (8),
Shohei Imamura (8). Internal/external ratio 0.59 (lowest of the named
clusters -- more cross-links to other communities than most).
**Representative films:** Zatoichi's Conspiracy, Harakiri, Hanzo the Razor,
The Castle of Sand, Zatoichi and the Fugitives.
**Alternatives considered:** "Chanbara / Samurai Cinema" (rejected -- covers
the Zatoichi/Misumi/Kobayashi swordplay films but not the Oshima/Shinoda/
Imamura New Wave side, both of which are strongly represented).
**Selection reason:** Genuinely bimodal (genre action cinema + Japanese New
Wave arthouse), but both halves are Japanese and separate cleanly by era
and genre from classic_japanese_cinema's family-drama/studio identity. A
single label covering both halves, rather than two overlapping national
labels, best reflects that it's one graph community.
**Confidence:** Medium -- coherent nationality, but the lower internal
ratio and two-genre split mean it's less tightly unified than the other
named clusters.

## hong_kong_taiwan_cinema (community 9)
**Display name:** Hong Kong & Taiwan Cinema
**Films:** 82 (3.8%)
**Evidence:** Years 1967-2025, median 1990. Top genres: Drama (51), Action
(48), Comedy (29). Top directors: John Woo (8), Wong Kar Wai (6), Jackie
Chan (5), Edward Yang (5), Hou Hsiao-hsien (5). Internal/external ratio
0.97 (highest of the named clusters -- almost entirely self-contained).
**Representative films:** The Eagle Shooting Heroes, Days of Being Wild,
Hard Boiled, The Heroic Trio.
**Selection reason:** Unchanged from the pre-import cluster of the same
name -- still the best-supported label; extremely high internal cohesion.
**Confidence:** High.

## scandinavian_bergman_circle (community 10)
**Display name:** Scandinavian Cinema & the Bergman Circle
**Films:** 80 (3.7%)
**Evidence:** Years 1917-2011, median 1955. Top genres: Drama (74), Romance
(21), Comedy (13). Top directors: Ingmar Bergman (31), Gustaf Molander (6),
Roberto Rossellini (4), Bo Widerberg (4), Mai Zetterling (3), Victor
Sjöström (3). Internal/external ratio 0.83.
**Representative films:** Autumn Sonata, Casablanca, Gaslight, Brink of
Life, For Whom the Bell Tolls, The Magician, Hour of the Wolf.
**Alternatives considered:** "Bergman & Scandinavian Cinema" (functionally
identical, reordered -- kept the version that reads as one cluster rather
than two); "Scandinavian Cinema" alone (rejected -- doesn't explain why
1940s Hollywood films like Casablanca and Gaslight are representative
members).
**Selection reason:** Ingmar Bergman is genuinely dominant (31/80 = 39%
credited-director share, well above any other director here), but several
of the highest-degree films in the community are 1940s Hollywood pictures
starring *actress* Ingrid Bergman (Casablanca, Gaslight, For Whom the Bell
Tolls, The Bells of St. Mary's) -- the shared-actor graph connected them via
her, not via Ingmar. The name is chosen to reflect both real signals rather
than picking one and mislabeling the other's presence as noise.
**Confidence:** Medium-high -- strong core identity, but the Ingrid Bergman
crossover means a a purely "Scandinavian" label would misdescribe several
of the cluster's own highest-degree films.

## czech_new_wave (community 11)
**Display name:** Czech New Wave
**Films:** 36 (1.7%)
**Evidence:** Years 1958-1987, median 1967. Top genres: Drama (26), Comedy
(19). Top directors: František Vláčil (5), Věra Chytilová (4), Miloš Forman
(3), Karel Zeman (2), Jiří Menzel (2), Evald Schorm (2). Internal/external
ratio 1.00 (fully self-contained).
**Representative films:** The Cassandra Cat, Courage for Every Day, The
Unfortunate Bridegroom, Closely Watched Trains.
**Selection reason:** Unchanged from the pre-import cluster -- a
well-documented, historically real film movement, and the data (era, all
Czech/Czechoslovak directors) strongly supports the label.
**Confidence:** High.

## silent_era_comedy (community 8)
**Display name:** Silent-Era Comedy
**Films:** 27 (1.2%)
**Evidence:** Years 1921-1957, median 1928. Top genres: Comedy (26), Drama
(11), Family (10). Top directors: Charles Chaplin (10), Clyde Bruckman
(3), Fred Newmeyer & Sam Taylor (3), Buster Keaton (2), Ted Wilde (2).
Internal/external ratio 0.68.
**Representative films:** The Milky Way, The Great Dictator, Movie Crazy,
Limelight, Speedy, Feet First, The Kid Brother.
**Alternatives considered:** "Chaplin & Keaton Circle" (rejected -- Chaplin
is the largest single share at 10/27 (37%) but not an outright majority,
and Keaton/Lloyd collaborators Newmeyer, Taylor, Bruckman, and Wilde
together outnumber him; a two-director name would still omit them).
**Selection reason:** This is a genuinely new community (did not exist as
a distinct named cluster before the import) -- era + genre are the
strongest shared signal across a slapstick-comedy ensemble that spans
several studios/collaborators, not one director's filmography.
**Confidence:** Medium-high -- clear genre/era identity, though a handful
of member films run later (Limelight 1952, at the edge of "silent era" in
name only, since Chaplin's late work is stylistically continuous with his
silent work and the community's median year is solidly silent-era 1928).

## soviet_cinema (community 21)
**Display name:** Soviet Cinema
**Films:** 24 (1.1%)
**Evidence:** Years 1957-2004, median 1967. Top genres: Drama (21), War
(6). Top directors: Kira Muratova (7), Andrei Tarkovsky (5), Sergei
Bondarchuk (4), Elem Klimov (2), Larisa Shepitko (2), Mikhail Kalatozov
(2). Internal/external ratio 1.00.
**Representative films:** Stalker, Mirror, Andrei Rublev, Solaris, Ivan's
Childhood.
**Selection reason:** Unchanged from the pre-import cluster -- all
directors are Soviet-era Russian/Ukrainian, fully self-contained community.
**Confidence:** High.

## satyajit_ray_indian (community 5)
**Display name:** Satyajit Ray & Indian Cinema
**Films:** 18 (0.8%)
**Evidence:** Years 1955-1994, median 1965. Top genres: Drama (16), Romance
(3). Top directors: Satyajit Ray (15/18 = 83%), Ritwik Ghatak (1), Mira
Nair (1), Shu Lea Cheang (1). Internal/external ratio 0.94.
**Representative films:** Devi, Apur Sansar, The Elephant God, Charulata,
The Home and the World.
**Selection reason:** Unchanged from the pre-import cluster. Single-director
naming is justified here per the design doc's rule ("unless that director
is genuinely dominant") -- 83% of the community's directorial credits are
Ray's.
**Confidence:** High.

---

## hiddenGems
**Display name:** Hidden Gems
**Films:** 270 (103 from 36 undersized Louvain communities below the
15-film floor, 3-9 films apiece, each individually too small/thin an
evidence base to name confidently on its own; 167 with no shared-actor edge
at all -- no cast data, or no actor in common with any other film in the
collection).
**Selection reason:** Pre-existing, established sitewide term for "real but
too-small-to-individually-name" communities, not a naming failure -- kept
as-is per "Use the project's established architecture ... unless a change
is required." Notably several of the folded-in communities *are*
individually coherent (e.g. a 6-film Ousmane Sembène/Djibril Diop Mambéty
Senegalese-cinema clique, a 5-film Charles Burnett/Billy Woodberry/Julie
Dash L.A. Rebellion clique, a 5-film Abbas Kiarostami-led Iranian clique) --
they're folded in for size, not incoherence. See
`src/cluster_naming_evidence.py --min-report-size 2` for their individual
evidence if any of them warrant promotion to a named cluster in a future
pass.
**Confidence:** N/A (not a single evidence-based identity by design).
